import { FetchCandidate } from './collected-urls-record'
import { IndexedPriorityQueue } from './fetch-candidate-queue'

export interface FetchCandidatePoolLimits {
    refillRunnableUrls: number
    maxQueuedUrlsPerOwner: number
}

export interface FetchCandidatePoolOptions extends FetchCandidatePoolLimits {
    maxConcurrentPerRegistrableDomain: number
}

export interface OriginPacing {
    originCrawlDelayMs(origin: string): number
    originNextImageStartAtMs(origin: string): number
}

export interface FetchCandidatePoolLease<T> {
    candidate: FetchCandidate
    context: T
    waitedMs: number
    release(): void
}

export interface FetchCandidatePoolAdmission {
    owner: FetchCandidatePoolOwner
    admitted(): void
}

type EntryState = 'queued' | 'expired' | 'taken' | 'withdrawn'

interface EntryPayload<T> {
    candidate: FetchCandidate
    context: T
    batch: PoolBatch<T>
}

interface PoolEntry<T> {
    /** Cleared once the entry leaves the pool, because a spent entry can stay in its origin array until compaction. */
    payload: EntryPayload<T> | undefined
    sequence: number
    enqueuedAtMs: number
    state: EntryState
    origin: OriginQueue<T>
}

interface OriginQueue<T> {
    origin: string
    domain: DomainQueue<T>
    entries: PoolEntry<T>[]
    head: number
    queued: number
    active: number
    pacedUntilMs: number
    delayed: DelayedOrigin<T> | undefined
    heapIndex: number
}

interface DomainQueue<T> {
    registrableDomain: string
    origins: Map<string, OriginQueue<T>>
    eligibleOrigins: IndexedPriorityQueue<OriginQueue<T>>
    active: number
    heapIndex: number
}

interface DelayedOrigin<T> {
    origin: OriginQueue<T>
    readyAtMs: number
    heapIndex: number
}

export interface PoolBatch<T> {
    readonly owner: FetchCandidatePoolOwner | undefined
    readonly entries: PoolEntry<T>[]
    queued: number
    expiryTimer: NodeJS.Timeout | undefined
}

const COMPACT_AFTER_ENTRIES = 64

/**
 * One queue of fetch candidates for the whole pod.
 *
 * Every consumer's batch adds its candidates here, and the fetch workers take them in age order
 * among the origins that are under their limits and past their crawl delay. The limits count
 * across the pod, so two batches from one partition cannot both claim a domain's slots.
 */
export class FetchCandidatePool<T> {
    private readonly domains = new Map<string, DomainQueue<T>>()
    private readonly eligibleDomains = new IndexedPriorityQueue<DomainQueue<T>>(domainHasOlderHead)
    private readonly delayedOrigins = new IndexedPriorityQueue<DelayedOrigin<T>>(
        (left, right) => left.readyAtMs < right.readyAtMs
    )
    private delayTimer: NodeJS.Timeout | undefined
    private delayTimerAtMs = Number.POSITIVE_INFINITY
    private expired: PoolEntry<T>[] = []
    private expiredHead = 0
    private waiters: (() => void)[] = []
    private sequence = 0
    private queuedCount = 0
    private closed = false

    constructor(
        private readonly options: FetchCandidatePoolOptions,
        private readonly pacing: OriginPacing
    ) {
        for (const [name, value] of Object.entries(options)) {
            if (!Number.isSafeInteger(value) || value <= 0) {
                throw new Error(`the image fetch candidate pool ${name} must be a positive integer, got ${value}`)
            }
        }
    }

    public get candidateCount(): number {
        return this.queuedCount + (this.expired.length - this.expiredHead)
    }

    public createOwner(): FetchCandidatePoolOwner {
        return new FetchCandidatePoolOwner(this.options)
    }

    public add(
        candidates: FetchCandidate[],
        context: T,
        deadlineMs: number,
        owner?: FetchCandidatePoolOwner
    ): PoolBatch<T> {
        const nowMs = Date.now()
        const batch: PoolBatch<T> = { owner, entries: [], queued: 0, expiryTimer: undefined }
        const touched = new Set<OriginQueue<T>>()
        for (const candidate of candidates) {
            const origin = this.originQueueFor(candidate)
            const entry: PoolEntry<T> = {
                payload: { candidate, context, batch },
                sequence: this.sequence++,
                enqueuedAtMs: nowMs,
                state: 'queued',
                origin,
            }
            origin.entries.push(entry)
            origin.queued += 1
            batch.entries.push(entry)
            batch.queued += 1
            this.queuedCount += 1
            owner?.recordQueued(candidate.registrableDomain)
            touched.add(origin)
        }
        for (const origin of touched) {
            this.refreshOrigin(origin, nowMs)
        }
        if (batch.queued > 0) {
            // The fetch path treats a candidate as late only once the clock is past the deadline.
            batch.expiryTimer = setTimeout(() => this.expire(batch), Math.max(0, deadlineMs - nowMs) + 1)
            batch.expiryTimer.unref()
            this.wake(1)
        }
        return batch
    }

    public async take(): Promise<FetchCandidatePoolLease<T> | undefined> {
        for (;;) {
            if (this.closed) {
                return undefined
            }
            const lease = this.tryTake()
            if (lease) {
                if (this.hasSelectableWork()) {
                    this.wake(1)
                }
                return lease
            }
            await new Promise<void>((resolve) => this.waiters.push(resolve))
        }
    }

    /** Removes the batch's candidates that no worker has taken, and returns how many it removed. */
    public withdraw(batch: PoolBatch<T>): number {
        const touched = new Set<OriginQueue<T>>()
        let withdrawn = 0
        for (const entry of batch.entries) {
            if (entry.state === 'queued') {
                this.leaveOriginQueue(entry)
                touched.add(entry.origin)
            } else if (entry.state !== 'expired') {
                continue
            }
            entry.state = 'withdrawn'
            entry.payload = undefined
            withdrawn += 1
        }
        this.clearExpiry(batch)
        const nowMs = Date.now()
        for (const origin of touched) {
            this.refreshOrigin(origin, nowMs)
        }
        return withdrawn
    }

    public close(): void {
        this.closed = true
        if (this.delayTimer) {
            clearTimeout(this.delayTimer)
            this.delayTimer = undefined
        }
        this.wake(this.waiters.length)
    }

    private tryTake(): FetchCandidatePoolLease<T> | undefined {
        const expiredEntry = this.nextExpired()
        if (expiredEntry) {
            expiredEntry.state = 'taken'
            return this.lease(expiredEntry, Date.now(), () => undefined)
        }
        const domain = this.eligibleDomains.peek()
        if (!domain) {
            return undefined
        }
        const origin = domain.eligibleOrigins.peek()!
        const entry = origin.entries[origin.head]
        const nowMs = Date.now()
        this.leaveOriginQueue(entry)
        entry.state = 'taken'
        origin.active += 1
        domain.active += 1
        const crawlDelayMs = this.pacing.originCrawlDelayMs(origin.origin)
        if (crawlDelayMs > 0) {
            origin.pacedUntilMs = Math.max(nowMs, origin.pacedUntilMs) + crawlDelayMs
        }
        this.refreshOrigin(origin, nowMs)
        let released = false
        return this.lease(entry, nowMs, () => {
            if (released) {
                return
            }
            released = true
            origin.active -= 1
            domain.active -= 1
            this.refreshOrigin(origin, Date.now())
            this.wake(1)
        })
    }

    private lease(entry: PoolEntry<T>, nowMs: number, release: () => void): FetchCandidatePoolLease<T> {
        const { candidate, context } = entry.payload!
        entry.payload = undefined
        return {
            candidate,
            context,
            waitedMs: Math.max(0, nowMs - entry.enqueuedAtMs),
            release,
        }
    }

    private leaveOriginQueue(entry: PoolEntry<T>): void {
        const { batch, candidate } = entry.payload!
        entry.origin.queued -= 1
        batch.queued -= 1
        this.queuedCount -= 1
        batch.owner?.recordLeft(candidate.registrableDomain)
        if (batch.queued === 0) {
            this.clearExpiry(batch)
        }
    }

    private expire(batch: PoolBatch<T>): void {
        batch.expiryTimer = undefined
        const touched = new Set<OriginQueue<T>>()
        for (const entry of batch.entries) {
            if (entry.state !== 'queued') {
                continue
            }
            this.leaveOriginQueue(entry)
            entry.state = 'expired'
            this.expired.push(entry)
            touched.add(entry.origin)
        }
        const nowMs = Date.now()
        for (const origin of touched) {
            this.refreshOrigin(origin, nowMs)
        }
        this.wake(1)
    }

    private clearExpiry(batch: PoolBatch<T>): void {
        if (batch.expiryTimer) {
            clearTimeout(batch.expiryTimer)
            batch.expiryTimer = undefined
        }
    }

    private nextExpired(): PoolEntry<T> | undefined {
        while (this.expiredHead < this.expired.length) {
            const entry = this.expired[this.expiredHead++]
            if (entry.state === 'expired') {
                this.compactExpired()
                return entry
            }
        }
        this.compactExpired()
        return undefined
    }

    private compactExpired(): void {
        if (this.expiredHead === this.expired.length) {
            this.expired = []
            this.expiredHead = 0
        } else if (this.expiredHead > COMPACT_AFTER_ENTRIES && this.expiredHead * 2 > this.expired.length) {
            this.expired = this.expired.slice(this.expiredHead)
            this.expiredHead = 0
        }
    }

    private hasSelectableWork(): boolean {
        for (let index = this.expiredHead; index < this.expired.length; index++) {
            if (this.expired[index].state === 'expired') {
                return true
            }
        }
        return this.eligibleDomains.size > 0
    }

    private wake(count: number): void {
        for (let woken = 0; woken < count && this.waiters.length > 0; woken++) {
            this.waiters.shift()!()
        }
    }

    private originQueueFor(candidate: FetchCandidate): OriginQueue<T> {
        let domain = this.domains.get(candidate.registrableDomain)
        if (!domain) {
            domain = {
                registrableDomain: candidate.registrableDomain,
                origins: new Map(),
                eligibleOrigins: new IndexedPriorityQueue<OriginQueue<T>>(originHasOlderHead),
                active: 0,
                heapIndex: -1,
            }
            this.domains.set(candidate.registrableDomain, domain)
        }
        let origin = domain.origins.get(candidate.origin)
        if (!origin) {
            origin = {
                origin: candidate.origin,
                domain,
                entries: [],
                head: 0,
                queued: 0,
                active: 0,
                pacedUntilMs: 0,
                delayed: undefined,
                heapIndex: -1,
            }
            domain.origins.set(candidate.origin, origin)
        }
        return origin
    }

    private refreshOrigin(origin: OriginQueue<T>, nowMs: number): void {
        this.advanceHead(origin)
        const domain = origin.domain
        if (origin.queued === 0 || origin.active >= this.options.maxConcurrentPerRegistrableDomain) {
            domain.eligibleOrigins.remove(origin)
            this.undelay(origin)
            if (origin.queued === 0 && origin.active === 0) {
                domain.origins.delete(origin.origin)
            }
        } else {
            const readyAtMs = Math.max(origin.pacedUntilMs, this.pacing.originNextImageStartAtMs(origin.origin))
            if (readyAtMs > nowMs) {
                domain.eligibleOrigins.remove(origin)
                this.delay(origin, readyAtMs)
            } else {
                this.undelay(origin)
                domain.eligibleOrigins.addOrUpdate(origin)
            }
        }
        this.refreshDomain(domain)
    }

    private refreshDomain(domain: DomainQueue<T>): void {
        if (domain.origins.size === 0 && domain.active === 0) {
            this.eligibleDomains.remove(domain)
            if (this.domains.get(domain.registrableDomain) === domain) {
                this.domains.delete(domain.registrableDomain)
            }
            return
        }
        if (domain.active < this.options.maxConcurrentPerRegistrableDomain && domain.eligibleOrigins.size > 0) {
            this.eligibleDomains.addOrUpdate(domain)
        } else {
            this.eligibleDomains.remove(domain)
        }
    }

    private advanceHead(origin: OriginQueue<T>): void {
        while (origin.head < origin.entries.length && origin.entries[origin.head].state !== 'queued') {
            origin.head += 1
        }
        if (origin.head === origin.entries.length) {
            origin.entries = []
            origin.head = 0
        } else if (origin.head > COMPACT_AFTER_ENTRIES && origin.head * 2 > origin.entries.length) {
            origin.entries = origin.entries.slice(origin.head)
            origin.head = 0
        }
    }

    private delay(origin: OriginQueue<T>, readyAtMs: number): void {
        if (origin.delayed) {
            origin.delayed.readyAtMs = readyAtMs
            this.delayedOrigins.addOrUpdate(origin.delayed)
        } else {
            origin.delayed = { origin, readyAtMs, heapIndex: -1 }
            this.delayedOrigins.addOrUpdate(origin.delayed)
        }
        this.armDelayTimer()
    }

    private undelay(origin: OriginQueue<T>): void {
        if (!origin.delayed) {
            return
        }
        this.delayedOrigins.remove(origin.delayed)
        origin.delayed = undefined
        this.armDelayTimer()
    }

    private armDelayTimer(): void {
        const next = this.delayedOrigins.peek()
        const nextAtMs = next?.readyAtMs ?? Number.POSITIVE_INFINITY
        if (nextAtMs === this.delayTimerAtMs || this.closed) {
            return
        }
        if (this.delayTimer) {
            clearTimeout(this.delayTimer)
            this.delayTimer = undefined
        }
        this.delayTimerAtMs = nextAtMs
        if (next) {
            this.delayTimer = setTimeout(() => this.releaseDelayedOrigins(), Math.max(0, nextAtMs - Date.now()))
            this.delayTimer.unref()
        }
    }

    private releaseDelayedOrigins(): void {
        this.delayTimer = undefined
        this.delayTimerAtMs = Number.POSITIVE_INFINITY
        const nowMs = Date.now()
        for (
            let next = this.delayedOrigins.peek();
            next && next.readyAtMs <= nowMs;
            next = this.delayedOrigins.peek()
        ) {
            this.delayedOrigins.remove(next)
            next.origin.delayed = undefined
            this.refreshOrigin(next.origin, nowMs)
        }
        this.armDelayTimer()
        if (this.eligibleDomains.size > 0) {
            this.wake(1)
        }
    }
}

/**
 * The window of one consumer: how much of its work waits in the pool.
 *
 * A registrable domain counts as runnable only up to its concurrency limit, because the pool never
 * runs more than that at once. A window full of one hot domain therefore still lets the consumer
 * read more, so its other domains do not wait in Kafka while candidate slots are free.
 */
export class FetchCandidatePoolOwner {
    private queued = 0
    private runnable = 0
    private pendingAdmissions = 0
    private readonly queuedByDomain = new Map<string, number>()
    private readonly roomWaiters = new Set<() => void>()

    constructor(private readonly options: FetchCandidatePoolOptions) {}

    public get queuedUrls(): number {
        return this.queued
    }

    public get runnableUrls(): number {
        return this.runnable
    }

    public beginAdmission(): FetchCandidatePoolAdmission {
        this.pendingAdmissions += 1
        let done = false
        return {
            owner: this,
            admitted: () => {
                if (done) {
                    return
                }
                done = true
                this.pendingAdmissions -= 1
                this.notifyIfRoom()
            },
        }
    }

    public hasRoom(): boolean {
        return (
            this.pendingAdmissions === 0 &&
            this.runnable < this.options.refillRunnableUrls &&
            this.queued < this.options.maxQueuedUrlsPerOwner
        )
    }

    /** Resolves true when the owner has room for another batch, or false when the wait runs out. */
    public waitForRoom(maxWaitMs: number): Promise<boolean> {
        if (this.hasRoom()) {
            return Promise.resolve(true)
        }
        return new Promise((resolve) => {
            const waiter = (): void => {
                clearTimeout(timer)
                resolve(true)
            }
            const timer = setTimeout(() => {
                this.roomWaiters.delete(waiter)
                resolve(false)
            }, maxWaitMs)
            this.roomWaiters.add(waiter)
        })
    }

    public recordQueued(registrableDomain: string): void {
        this.queued += 1
        this.changeDomainCount(registrableDomain, 1)
    }

    public recordLeft(registrableDomain: string): void {
        this.queued -= 1
        this.changeDomainCount(registrableDomain, -1)
        this.notifyIfRoom()
    }

    private changeDomainCount(registrableDomain: string, delta: number): void {
        const limit = this.options.maxConcurrentPerRegistrableDomain
        const before = this.queuedByDomain.get(registrableDomain) ?? 0
        const after = before + delta
        if (after === 0) {
            this.queuedByDomain.delete(registrableDomain)
        } else {
            this.queuedByDomain.set(registrableDomain, after)
        }
        this.runnable += Math.min(after, limit) - Math.min(before, limit)
    }

    private notifyIfRoom(): void {
        if (this.roomWaiters.size === 0 || !this.hasRoom()) {
            return
        }
        const waiters = [...this.roomWaiters]
        this.roomWaiters.clear()
        for (const waiter of waiters) {
            waiter()
        }
    }
}

function originHeadSequence<T>(origin: OriginQueue<T>): number {
    return origin.entries[origin.head].sequence
}

function originHasOlderHead<T>(left: OriginQueue<T>, right: OriginQueue<T>): boolean {
    return originHeadSequence(left) < originHeadSequence(right)
}

function domainHasOlderHead<T>(left: DomainQueue<T>, right: DomainQueue<T>): boolean {
    return originHeadSequence(left.eligibleOrigins.peek()!) < originHeadSequence(right.eligibleOrigins.peek()!)
}
