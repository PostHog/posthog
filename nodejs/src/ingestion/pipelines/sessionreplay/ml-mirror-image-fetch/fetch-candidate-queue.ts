import FastPriorityQueue from 'fastpriorityqueue'

import { FetchCandidate } from './collected-urls-record'

export type FetchCandidateQueueAction = 'fetch' | 'republish_low_origin_diversity'

export interface LowOriginDiversitySnapshot {
    origins: number
    candidates: number
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
    available: boolean
}

interface RegistrableDomainQueue {
    registrableDomain: string
    origins: Map<string, OriginQueue>
    availableOrigins: FastPriorityQueue<OriginQueue>
    active: number
    heapIndex: number
}

class AvailableDomainQueue {
    private readonly heap: RegistrableDomainQueue[] = []

    public get size(): number {
        return this.heap.length
    }

    public addOrUpdate(domain: RegistrableDomainQueue): void {
        if (domain.heapIndex < 0) {
            domain.heapIndex = this.heap.length
            this.heap.push(domain)
            this.siftUp(domain.heapIndex)
            return
        }
        this.rebalance(domain.heapIndex)
    }

    public remove(domain: RegistrableDomainQueue): void {
        const index = domain.heapIndex
        if (index < 0) {
            return
        }
        const last = this.heap.pop()!
        domain.heapIndex = -1
        if (index === this.heap.length) {
            return
        }
        this.heap[index] = last
        last.heapIndex = index
        this.rebalance(index)
    }

    public poll(): RegistrableDomainQueue | undefined {
        const domain = this.heap[0]
        if (domain) {
            this.remove(domain)
        }
        return domain
    }

    private rebalance(index: number): void {
        const parentIndex = Math.floor((index - 1) / 2)
        if (index > 0 && domainQueueHasPriority(this.heap[index], this.heap[parentIndex])) {
            this.siftUp(index)
        } else {
            this.siftDown(index)
        }
    }

    private siftUp(startIndex: number): void {
        let index = startIndex
        while (index > 0) {
            const parentIndex = Math.floor((index - 1) / 2)
            if (!domainQueueHasPriority(this.heap[index], this.heap[parentIndex])) {
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
                rightIndex < this.heap.length && domainQueueHasPriority(this.heap[rightIndex], this.heap[leftIndex])
                    ? rightIndex
                    : leftIndex
            if (!domainQueueHasPriority(this.heap[childIndex], this.heap[index])) {
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
    minimumActiveOrigins: number
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
            candidatesByCanonicalRef.set(candidate.originalRef, foldDuplicateCandidate(existing, candidate))
        } else {
            candidatesByCanonicalRef.set(candidate.originalRef, candidate)
        }
    }
    return { candidates: [...candidatesByCanonicalRef.values()], duplicateCount }
}

export class FetchCandidateQueue {
    private readonly domains = new Map<string, RegistrableDomainQueue>()
    private readonly availableDomains = new AvailableDomainQueue()
    private waitingCandidates = 0
    private waitingCandidatesWithoutDiversityDeferral = 0
    private remainingOrigins = 0
    private lowOriginDiversityStarted = false
    private lowOriginDiversityProgressRemaining: number
    private initialSchedulableSlots = 0
    private aborted = false

    constructor(
        candidates: FetchCandidate[],
        private readonly options: FetchCandidateQueueOptions
    ) {
        this.lowOriginDiversityProgressRemaining = options.lowOriginDiversityProgress
        const deduplicated = deduplicateFetchCandidates(candidates)
        let sequence = 0
        for (const candidate of deduplicated.candidates) {
            let domain = this.domains.get(candidate.registrableDomain)
            if (!domain) {
                domain = {
                    registrableDomain: candidate.registrableDomain,
                    origins: new Map(),
                    availableOrigins: new FastPriorityQueue<OriginQueue>(originQueueHasPriority),
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
                    sequence: sequence++,
                    active: 0,
                    available: false,
                }
                domain.origins.set(candidate.origin, originQueue)
                this.remainingOrigins += 1
            }
            originQueue.candidates.push(candidate)
            this.waitingCandidates += 1
            if (candidate.lowOriginDiversityDeferred !== true) {
                this.waitingCandidatesWithoutDiversityDeferral += 1
            }
        }
        for (const domain of this.domains.values()) {
            let domainCandidateCount = 0
            for (const origin of domain.origins.values()) {
                domainCandidateCount += originCandidateCount(origin)
                this.refreshOriginSelection(domain, origin)
            }
            this.initialSchedulableSlots += Math.min(
                domainCandidateCount,
                this.options.maxConcurrentPerRegistrableDomain
            )
            this.refreshDomainSelection(domain)
        }
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

    public abort(): void {
        this.aborted = true
    }

    public take(): FetchCandidateLease | undefined {
        if (this.aborted) {
            return undefined
        }
        const selected = this.takeLargestAvailableOrigin()
        if (!selected) {
            return undefined
        }
        const lowOriginDiversity =
            this.lowOriginDiversityStarted ||
            (this.remainingOrigins < this.options.minimumActiveOrigins &&
                this.waitingCandidatesWithoutDiversityDeferral > this.options.lowOriginDiversityRepublishThreshold)
        const lowOriginDiversityStarted =
            lowOriginDiversity && !this.lowOriginDiversityStarted
                ? { origins: this.remainingOrigins, candidates: this.waitingCandidates }
                : undefined
        if (lowOriginDiversityStarted) {
            this.lowOriginDiversityStarted = true
        }
        const candidate = selected.origin.candidates[selected.origin.head++]!
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
                selected.domain.active = Math.max(0, selected.domain.active - 1)
                selected.origin.active = Math.max(0, selected.origin.active - 1)
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

    private takeLargestAvailableOrigin(): { domain: RegistrableDomainQueue; origin: OriginQueue } | undefined {
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
            origin.available = false
            domain.active += 1
            origin.active += 1
            return { domain, origin }
        }
    }

    private refreshOriginSelection(domain: RegistrableDomainQueue, origin: OriginQueue): void {
        if (
            origin.available ||
            originCandidateCount(origin) === 0 ||
            origin.active >= this.options.maxConcurrentPerRegistrableDomain
        ) {
            return
        }
        origin.available = true
        domain.availableOrigins.add(origin)
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
    return (
        originCandidateCount(left) > originCandidateCount(right) ||
        (originCandidateCount(left) === originCandidateCount(right) && left.sequence < right.sequence)
    )
}

function originCandidateCount(origin: OriginQueue): number {
    return origin.candidates.length - origin.head
}

function domainQueueHasPriority(left: RegistrableDomainQueue, right: RegistrableDomainQueue): boolean {
    const leftOrigin = left.availableOrigins.peek()!
    const rightOrigin = right.availableOrigins.peek()!
    return (
        originCandidateCount(leftOrigin) > originCandidateCount(rightOrigin) ||
        (originCandidateCount(leftOrigin) === originCandidateCount(rightOrigin) &&
            leftOrigin.sequence < rightOrigin.sequence)
    )
}

function foldDuplicateCandidate(left: FetchCandidate, right: FetchCandidate): FetchCandidate {
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
