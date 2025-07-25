import { Client as CassandraClient, types as CassandraTypes } from 'cassandra-driver'

export interface BehavioralCounterRow {
    team_id: number
    filter_hash: string
    person_id: string
    date: string
    count: number
}

export interface CounterUpdate {
    teamId: number
    filterHash: string
    personId: string
    date: string
}

export class BehavioralCounterRepository {
    constructor(private cassandra: CassandraClient) {}

    /**
     * Maps a Cassandra row to a BehavioralCounterRow
     */
    private mapRowToBehavioralCounter(row: any): BehavioralCounterRow {
        return {
            team_id: row.team_id,
            filter_hash: row.filter_hash,
            person_id: row.person_id.toString(),
            date: row.date,
            count: row.count.toNumber(),
        }
    }

    /**
     * Gets a specific behavioral counter
     */
    async getCounter(params: {
        teamId: number
        filterHash: string
        personId: string
        date: string
    }): Promise<BehavioralCounterRow | null> {
        const { teamId, filterHash, personId, date } = params
        const result = await this.cassandra.execute(
            'SELECT team_id, filter_hash, person_id, date, count FROM behavioral_event_counters WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
            [teamId, filterHash, CassandraTypes.Uuid.fromString(personId), date],
            { prepare: true }
        )

        if (result.rows.length === 0) {
            return null
        }

        const row = result.rows[0]
        return this.mapRowToBehavioralCounter(row)
    }

    /**
     * Gets all behavioral counters for a team
     */
    async getCountersForTeam(teamId: number): Promise<BehavioralCounterRow[]> {
        const result = await this.cassandra.execute(
            'SELECT team_id, filter_hash, person_id, date, count FROM behavioral_event_counters WHERE team_id = ?',
            [teamId],
            { prepare: true }
        )

        return result.rows.map((row) => this.mapRowToBehavioralCounter(row))
    }

    /**
     * Batch increments multiple behavioral counters
     */
    async batchIncrementCounters(updates: CounterUpdate[]): Promise<void> {
        if (updates.length === 0) {
            return
        }

        const batch = updates.map((update) => ({
            query: 'UPDATE behavioral_event_counters SET count = count + 1 WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
            params: [update.teamId, update.filterHash, CassandraTypes.Uuid.fromString(update.personId), update.date],
        }))

        await this.cassandra.batch(batch, { prepare: true, logged: false })
    }
}
