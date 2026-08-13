import { createHash } from 'node:crypto'

/** This many teams keep their name. The class sums everything else into `other`. */
const DEFAULT_TOP_N = 20

/**
 * Counters held to find those teams, wider than the reported list so that the reported list is
 * right. Space-Saving holds any team whose share is above one over this number of counters. At 200
 * counters that is half a percent of the lane's volume.
 *
 * The count is bounded because the team ID space is in the low millions. A map of every team ever
 * seen is the unbounded growth this class exists to avoid.
 */
const TRACKED_MULTIPLE = 10

/**
 * Registers of the estimator. 2^12 gives about 1.6% error for a few kilobytes, which is far finer
 * than any decision this number feeds.
 */
const HLL_REGISTER_BITS = 12
const HLL_REGISTERS = 1 << HLL_REGISTER_BITS

/**
 * How much of the lane one team uses, without a `team_id` label on anything.
 *
 * The team ID space is in the low millions. A label of that cardinality is unbounded twice over: in
 * the time series database, and in the memory of this process, because prom-client holds every label
 * combination for the life of the pod. So this class holds the identities of the busiest teams,
 * bounded, and counts everything else without a name.
 *
 * Requirements 29, 30, and 31.
 */
export class TeamVolume {
    private readonly counts = new Map<string, number>()
    private readonly registers = new Uint8Array(HLL_REGISTERS)
    private readonly capacity: number
    private total = 0

    constructor(private readonly topN: number = DEFAULT_TOP_N) {
        this.capacity = topN * TRACKED_MULTIPLE
    }

    /**
     * Space-Saving: a full map replaces its smallest counter rather than grows.
     *
     * The replacement inherits the count it displaced, so a team that keeps arriving climbs past the
     * churn of teams seen once. A flood of quiet teams therefore cannot push a busy team out, and
     * that flood is what someone who spreads traffic over many project tokens produces.
     */
    public record(team: string, count = 1): void {
        this.total += count
        this.observeDistinct(team)

        const seen = this.counts.get(team)
        if (seen !== undefined) {
            this.counts.set(team, seen + count)
            return
        }
        if (this.counts.size < this.capacity) {
            this.counts.set(team, count)
            return
        }
        const smallest = this.smallest()
        this.counts.delete(smallest.team)
        this.counts.set(team, smallest.count + count)
    }

    private smallest(): { team: string; count: number } {
        let team = ''
        let count = Infinity
        for (const [candidate, candidateCount] of this.counts) {
            if (candidateCount < count) {
                team = candidate
                count = candidateCount
            }
        }
        return { team, count }
    }

    /**
     * The busiest teams by name, and everything else summed as `other`.
     *
     * This sorts on each read rather than keeps an order on each record, because a read happens once
     * for each scrape and a record happens once for each URL.
     */
    public top(): { team: string; count: number }[] {
        const sorted = [...this.counts].sort((left, right) => right[1] - left[1])
        const named = sorted.slice(0, this.topN).map(([team, count]) => ({ team, count }))
        // Everything this pod handled, less what the named rows account for. This reads the running
        // total, because the counters of the untracked teams no longer exist.
        const rest = this.total - named.reduce((sum, { count }) => sum + count, 0)
        return rest > 0 ? [...named, { team: 'other', count: rest }] : named
    }

    /**
     * About how many distinct teams this pod saw. HyperLogLog rather than a set, because a set of a
     * million team IDs is hundreds of megabytes, and a reader only ever takes the order of magnitude.
     */
    public distinctTeams(): number {
        let sum = 0
        let empty = 0
        for (const rank of this.registers) {
            sum += 2 ** -rank
            if (rank === 0) {
                empty++
            }
        }
        const estimate = (ALPHA * HLL_REGISTERS * HLL_REGISTERS) / sum
        // The estimator is biased below this point, and a count of the untouched registers is exact there.
        if (estimate <= 2.5 * HLL_REGISTERS && empty > 0) {
            return Math.round(HLL_REGISTERS * Math.log(HLL_REGISTERS / empty))
        }
        return Math.round(estimate)
    }

    /** Counters held right now, which never pass the capacity. */
    public get trackedTeams(): number {
        return this.counts.size
    }

    private observeDistinct(team: string): void {
        // The team ID is already an HMAC on this topic, but it is not uniform across the register
        // index and the leading zero count, and the estimator needs both of them to be uniform.
        const digest = createHash('sha1').update(team).digest()
        const index = digest.readUInt16BE(0) % HLL_REGISTERS
        const rank = leadingZeros(digest.readUInt32BE(2)) + 1
        if (rank > this.registers[index]) {
            this.registers[index] = rank
        }
    }
}

/** The bias constant for this register count, from the HyperLogLog paper. */
const ALPHA = 0.7213 / (1 + 1.079 / HLL_REGISTERS)

function leadingZeros(value: number): number {
    return value === 0 ? 32 : Math.clz32(value)
}
