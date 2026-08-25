import { FetchCandidate } from './collected-urls-record'

export type FetchCandidateQueueAction = 'fetch' | 'republish_low_origin_diversity'

export interface LowOriginDiversitySnapshot {
    origins: number
    candidates: number
    requestSlots: number
}

export interface FetchCandidateLease {
    candidate: FetchCandidate
    action: FetchCandidateQueueAction
    lowOriginDiversityStarted?: LowOriginDiversitySnapshot
    release(): void
}

interface OriginQueue {
    origin: string
    candidates: FetchCandidate[]
    head: number
    sequence: number
    active: number
    initialCandidateCount: number
    targetConcurrent: number
    heapIndex: number
}

interface RegistrableDomainQueue {
    registrableDomain: string
    origins: Map<string, OriginQueue>
    availableOrigins: IndexedPriorityQueue<OriginQueue>
    initialCandidateCount: number
    waitingCandidateCount: number
    targetConcurrent: number
    sequence: number
    active: number
    heapIndex: number
}

interface IndexedPriorityQueueItem {
    heapIndex: number
}

class IndexedPriorityQueue<T extends IndexedPriorityQueueItem> {
    private readonly heap: T[] = []

    constructor(private readonly hasPriority: (left: T, right: T) => boolean) {}

    public get size(): number {
        return this.heap.length
    }

    public addOrUpdate(item: T): void {
        if (item.heapIndex < 0) {
            item.heapIndex = this.heap.length
            this.heap.push(item)
            this.siftUp(item.heapIndex)
            return
        }
        this.rebalance(item.heapIndex)
    }

    public remove(item: T): void {
        const index = item.heapIndex
        if (index < 0) {
            return
        }
        const last = this.heap.pop()!
        item.heapIndex = -1
        if (index === this.heap.length) {
            return
        }
        this.heap[index] = last
        last.heapIndex = index
        this.rebalance(index)
    }

    public peek(): T | undefined {
        return this.heap[0]
    }

    public poll(): T | undefined {
        const item = this.heap[0]
        if (item) {
            this.remove(item)
        }
        return item
    }

    private rebalance(index: number): void {
        const parentIndex = Math.floor((index - 1) / 2)
        if (index > 0 && this.hasPriority(this.heap[index], this.heap[parentIndex])) {
            this.siftUp(index)
        } else {
            this.siftDown(index)
        }
    }

    private siftUp(startIndex: number): void {
        let index = startIndex
        while (index > 0) {
            const parentIndex = Math.floor((index - 1) / 2)
            if (!this.hasPriority(this.heap[index], this.heap[parentIndex])) {
                return
            }
            this.swap(index, parentIndex)
            index = parentIndex
        }
    }

    private siftDown(startIndex: number): void {
        let index = startIndex
        for (;;) {
            const leftIndex = index * 2 + 1
            if (leftIndex >= this.heap.length) {
                return
            }
            const rightIndex = leftIndex + 1
            const childIndex =
                rightIndex < this.heap.length && this.hasPriority(this.heap[rightIndex], this.heap[leftIndex])
                    ? rightIndex
                    : leftIndex
            if (!this.hasPriority(this.heap[childIndex], this.heap[index])) {
                return
            }
            this.swap(index, childIndex)
            index = childIndex
        }
    }

    private swap(leftIndex: number, rightIndex: number): void {
        const left = this.heap[leftIndex]
        const right = this.heap[rightIndex]
        this.heap[leftIndex] = right
        this.heap[rightIndex] = left
        left.heapIndex = rightIndex
        right.heapIndex = leftIndex
    }
}

export interface FetchCandidateQueueOptions {
    maxConcurrentPerRegistrableDomain: number
    maxInFlightRequests: number
    lowOriginDiversityMinimumRequestSlots: number
    lowOriginDiversityRepublishThreshold: number
    lowOriginDiversityProgress: number
}

export interface DeduplicatedFetchCandidates {
    candidates: FetchCandidate[]
    duplicateCount: number
}

export function deduplicateFetchCandidates(candidates: FetchCandidate[]): DeduplicatedFetchCandidates {
    const candidatesByCanonicalRef = new Map<string, FetchCandidate>()
    let duplicateCount = 0
    for (const candidate of candidates) {
        const existing = candidatesByCanonicalRef.get(candidate.originalRef)
        if (existing) {
            duplicateCount += 1
            candidatesByCanonicalRef.set(candidate.originalRef, mergeDuplicateFetchCandidates(existing, candidate))
        } else {
            candidatesByCanonicalRef.set(candidate.originalRef, candidate)
        }
    }
    return { candidates: [...candidatesByCanonicalRef.values()], duplicateCount }
}

export class FetchCandidateQueue {
    private readonly domains = new Map<string, RegistrableDomainQueue>()
    private readonly availableDomains = new IndexedPriorityQueue<RegistrableDomainQueue>(domainQueueHasPriority)
    private waitingCandidates = 0
    private waitingCandidatesWithoutDiversityDeferral = 0
    private remainingOrigins = 0
    private lowOriginDiversityStarted = false
    private lowOriginDiversityProgressRemaining: number
    private initialSchedulableSlots = 0
    private remainingSchedulableSlots = 0
    private aborted = false

    constructor(
        candidates: FetchCandidate[],
        private readonly options: FetchCandidateQueueOptions
    ) {
        this.lowOriginDiversityProgressRemaining = options.lowOriginDiversityProgress
        const deduplicated = deduplicateFetchCandidates(candidates)
        let domainSequence = 0
        let originSequence = 0
        for (const candidate of deduplicated.candidates) {
            let domain = this.domains.get(candidate.registrableDomain)
            if (!domain) {
                domain = {
                    registrableDomain: candidate.registrableDomain,
                    origins: new Map(),
                    availableOrigins: new IndexedPriorityQueue<OriginQueue>(originQueueHasPriority),
                    initialCandidateCount: 0,
                    waitingCandidateCount: 0,
                    targetConcurrent: 0,
                    sequence: domainSequence++,
                    active: 0,
                    heapIndex: -1,
                }
                this.domains.set(candidate.registrableDomain, domain)
            }
            let originQueue = domain.origins.get(candidate.origin)
            if (!originQueue) {
                originQueue = {
                    origin: candidate.origin,
                    candidates: [],
                    head: 0,
                    sequence: originSequence++,
                    active: 0,
                    initialCandidateCount: 0,
                    targetConcurrent: 0,
                    heapIndex: -1,
                }
                domain.origins.set(candidate.origin, originQueue)
                this.remainingOrigins += 1
            }
            originQueue.candidates.push(candidate)
            originQueue.initialCandidateCount += 1
            domain.initialCandidateCount += 1
            domain.waitingCandidateCount += 1
            this.waitingCandidates += 1
            if (candidate.lowOriginDiversityDeferred !== true) {
                this.waitingCandidatesWithoutDiversityDeferral += 1
            }
        }
        allocateConcurrentTargets(
            [...this.domains.values()],
            this.options.maxInFlightRequests,
            this.options.maxConcurrentPerRegistrableDomain
        )
        for (const domain of this.domains.values()) {
            allocateConcurrentTargets(
                [...domain.origins.values()],
                domain.targetConcurrent,
                this.options.maxConcurrentPerRegistrableDomain
            )
            for (const origin of domain.origins.values()) {
                this.refreshOriginSelection(domain, origin)
            }
            this.initialSchedulableSlots += Math.min(
                domain.initialCandidateCount,
                this.options.maxConcurrentPerRegistrableDomain
            )
            this.refreshDomainSelection(domain)
        }
        this.remainingSchedulableSlots = this.initialSchedulableSlots
    }

    public get candidateCount(): number {
        return this.waitingCandidates
    }

    public get originCount(): number {
        return this.remainingOrigins
    }

    public get selectableRegistrableDomainCount(): number {
        return this.availableDomains.size
    }

    public get schedulableSlotsAtStart(): number {
        return this.initialSchedulableSlots
    }

    public availableRequestSlotsAtStart(availableConnections: (registrableDomain: string) => number): number {
        let slots = 0
        for (const domain of this.domains.values()) {
            slots += Math.min(domain.initialCandidateCount, availableConnections(domain.registrableDomain))
        }
        return slots
    }

    public abort(): void {
        this.aborted = true
    }

    public take(): FetchCandidateLease | undefined {
        if (this.aborted) {
            return undefined
        }
        const selected = this.takeHighestPriorityOrigin()
        if (!selected) {
            return undefined
        }
        const remainingRequestSlots = Math.min(this.remainingSchedulableSlots, this.options.maxInFlightRequests)
        const lowOriginDiversity =
            this.lowOriginDiversityStarted ||
            (remainingRequestSlots < this.options.lowOriginDiversityMinimumRequestSlots &&
                this.waitingCandidatesWithoutDiversityDeferral > this.options.lowOriginDiversityRepublishThreshold)
        const lowOriginDiversityStarted =
            lowOriginDiversity && !this.lowOriginDiversityStarted
                ? {
                      origins: this.remainingOrigins,
                      candidates: this.waitingCandidates,
                      requestSlots: remainingRequestSlots,
                  }
                : undefined
        if (lowOriginDiversityStarted) {
            this.lowOriginDiversityStarted = true
        }
        const candidate = selected.origin.candidates[selected.origin.head++]!
        selected.domain.waitingCandidateCount -= 1
        this.refreshOriginSelection(selected.domain, selected.origin)
        this.refreshDomainSelection(selected.domain)
        const candidateCanReceiveDiversityDeferral = candidate.lowOriginDiversityDeferred !== true
        const action: FetchCandidateQueueAction =
            lowOriginDiversity && this.lowOriginDiversityProgressRemaining <= 0 && candidateCanReceiveDiversityDeferral
                ? 'republish_low_origin_diversity'
                : 'fetch'
        if (lowOriginDiversity && action === 'fetch' && this.lowOriginDiversityProgressRemaining > 0) {
            this.lowOriginDiversityProgressRemaining -= 1
        }

        this.waitingCandidates -= 1
        if (candidateCanReceiveDiversityDeferral) {
            this.waitingCandidatesWithoutDiversityDeferral -= 1
        }
        let released = false
        return {
            candidate,
            action,
            lowOriginDiversityStarted,
            release: () => {
                if (released) {
                    return
                }
                released = true
                const requestSlotsBeforeRelease = Math.min(
                    selected.domain.active + selected.domain.waitingCandidateCount,
                    this.options.maxConcurrentPerRegistrableDomain
                )
                selected.domain.active = Math.max(0, selected.domain.active - 1)
                selected.origin.active = Math.max(0, selected.origin.active - 1)
                const requestSlotsAfterRelease = Math.min(
                    selected.domain.active + selected.domain.waitingCandidateCount,
                    this.options.maxConcurrentPerRegistrableDomain
                )
                this.remainingSchedulableSlots -= requestSlotsBeforeRelease - requestSlotsAfterRelease
                if (originCandidateCount(selected.origin) === 0 && selected.origin.active === 0) {
                    selected.domain.origins.delete(selected.origin.origin)
                    this.remainingOrigins -= 1
                } else {
                    this.refreshOriginSelection(selected.domain, selected.origin)
                }
                if (selected.domain.origins.size === 0) {
                    this.availableDomains.remove(selected.domain)
                    this.domains.delete(selected.domain.registrableDomain)
                } else {
                    this.refreshDomainSelection(selected.domain)
                }
            },
        }
    }

    private takeHighestPriorityOrigin(): { domain: RegistrableDomainQueue; origin: OriginQueue } | undefined {
        for (;;) {
            const domain = this.availableDomains.poll()
            if (!domain) {
                return undefined
            }
            if (domain.active >= this.options.maxConcurrentPerRegistrableDomain) {
                continue
            }
            const origin = domain.availableOrigins.poll()
            if (!origin) {
                continue
            }
            domain.active += 1
            origin.active += 1
            return { domain, origin }
        }
    }

    private refreshOriginSelection(domain: RegistrableDomainQueue, origin: OriginQueue): void {
        if (originCandidateCount(origin) === 0 || origin.active >= this.options.maxConcurrentPerRegistrableDomain) {
            domain.availableOrigins.remove(origin)
            return
        }
        domain.availableOrigins.addOrUpdate(origin)
    }

    private refreshDomainSelection(domain: RegistrableDomainQueue): void {
        const origin = domain.availableOrigins.peek()
        if (!origin || domain.active >= this.options.maxConcurrentPerRegistrableDomain) {
            this.availableDomains.remove(domain)
            return
        }
        this.availableDomains.addOrUpdate(domain)
    }
}

function originQueueHasPriority(left: OriginQueue, right: OriginQueue): boolean {
    const leftDistance = left.targetConcurrent - left.active
    const rightDistance = right.targetConcurrent - right.active
    return (
        leftDistance > rightDistance ||
        (leftDistance === rightDistance && originCandidateCount(left) > originCandidateCount(right)) ||
        (leftDistance === rightDistance &&
            originCandidateCount(left) === originCandidateCount(right) &&
            left.sequence < right.sequence)
    )
}

function originCandidateCount(origin: OriginQueue): number {
    return origin.candidates.length - origin.head
}

function domainQueueHasPriority(left: RegistrableDomainQueue, right: RegistrableDomainQueue): boolean {
    const leftDistance = left.targetConcurrent - left.active
    const rightDistance = right.targetConcurrent - right.active
    return (
        leftDistance > rightDistance ||
        (leftDistance === rightDistance && left.waitingCandidateCount > right.waitingCandidateCount) ||
        (leftDistance === rightDistance &&
            left.waitingCandidateCount === right.waitingCandidateCount &&
            left.sequence < right.sequence)
    )
}

interface ConcurrentTarget {
    initialCandidateCount: number
    targetConcurrent: number
}

function allocateConcurrentTargets<T extends ConcurrentTarget>(
    queues: T[],
    totalCapacity: number,
    maximumPerQueue: number
): void {
    let remainingCapacity = Math.min(
        totalCapacity,
        queues.reduce((sum, queue) => sum + queue.initialCandidateCount, 0)
    )
    let remainingWeight = queues.reduce((sum, queue) => sum + queue.initialCandidateCount, 0)
    let remainingQueues = queues

    while (remainingQueues.length > 0 && remainingCapacity > 0 && remainingWeight > 0) {
        const queuesAtLimit = remainingQueues.filter((queue) => {
            const proportionalTarget = (remainingCapacity * queue.initialCandidateCount) / remainingWeight
            return proportionalTarget >= Math.min(maximumPerQueue, queue.initialCandidateCount)
        })
        if (queuesAtLimit.length === 0) {
            for (const queue of remainingQueues) {
                queue.targetConcurrent = (remainingCapacity * queue.initialCandidateCount) / remainingWeight
            }
            return
        }
        const queuesAtLimitSet = new Set(queuesAtLimit)
        for (const queue of queuesAtLimit) {
            queue.targetConcurrent = Math.min(maximumPerQueue, queue.initialCandidateCount)
            remainingCapacity -= queue.targetConcurrent
            remainingWeight -= queue.initialCandidateCount
        }
        remainingQueues = remainingQueues.filter((queue) => !queuesAtLimitSet.has(queue))
    }
}

export function mergeDuplicateFetchCandidates(left: FetchCandidate, right: FetchCandidate): FetchCandidate {
    let preferredRoute = left
    if (
        right.remainingHops < left.remainingHops ||
        (right.remainingHops === left.remainingHops && right.republishCount > left.republishCount) ||
        (right.remainingHops === left.remainingHops &&
            right.republishCount === left.republishCount &&
            right.fetchCount > left.fetchCount)
    ) {
        preferredRoute = right
    }
    const latestState = left.republishCount >= right.republishCount ? left : right
    return {
        ...preferredRoute,
        remainingHops: Math.min(left.remainingHops, right.remainingHops),
        notBeforeMs: Math.max(left.notBeforeMs, right.notBeforeMs),
        firstSeenAtMs: Math.min(left.firstSeenAtMs, right.firstSeenAtMs),
        fetchCount: Math.max(left.fetchCount, right.fetchCount),
        republishCount: Math.max(left.republishCount, right.republishCount),
        lastRepublishReason: latestState.lastRepublishReason,
        lowOriginDiversityDeferred:
            left.lowOriginDiversityDeferred === true || right.lowOriginDiversityDeferred === true ? true : undefined,
    }
}
