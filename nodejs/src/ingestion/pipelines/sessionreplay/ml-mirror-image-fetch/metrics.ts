import { Counter, Gauge, Histogram } from 'prom-client'

import type { RepublishReason, UrlDropReason } from './collected-urls-record'
import type { AttemptOutcome } from './fetch-runner'
import type { FrontierDeadLetterReason } from './frontier-dead-letter-sink'
import type { FetchRefusalReason, RequestScheduleBlockReason, TransientFetchOutcome } from './image-fetcher'

/** What the in-flight gauge reads. Narrower than `ConcurrencyController`, so the metrics do not depend on the whole of it. */
export interface InFlightCount {
    readonly running: number
}

/** What the budget gauges read. Narrower than `HostBudget`, so the metrics do not depend on the whole of it. */
export interface BudgetCounts {
    readonly trackedRegistrableDomains: number
    readonly trackedOrigins: number
    readonly evictedWhileBlocked: number
    blockedRegistrableDomains(nowMs: number): number
}

export type DedupScope = 'batch' | 'store'
export type SchedulerWaitScope = 'origin_crawl_delay' | 'registrable_domain_rate' | 'request_capacity'
export type HttpRequestOutcome = '2xx' | '3xx' | '4xx' | '5xx' | 'other' | 'network_error'
export type RepublishDestination = 'frontier' | 'delay'
export type RepublishTopic = 'frontier' | 'retry_1m' | 'retry_10m' | 'retry_1h'
type BatchDiversityScope = 'origin' | 'registrable_domain'
type PartitionUrlStage = 'parsed' | 'accepted' | 'unique' | 'fetchable' | 'not_ready' | 'store_deduped'
type PartitionAttemptDisposition = 'completed' | 'republished'
type PolicyAndBudgetReason = FetchRefusalReason | RequestScheduleBlockReason | 'none'

const BATCH_DIVERSITY_TOP_COUNTS = [1, 5, 10] as const

export class ImageFetchConsumerMetrics {
    private static readonly fetchable = new Counter({
        name: 'ml_image_fetch_consumer_fetchable_total',
        help: 'URLs that passed every check and would have been fetched. In dry run no request is sent, so this is the offered rate rather than the sent rate',
    })
    /**
     * `batch` costs only memory, while `store` costs a shared-store read.
     */
    private static readonly deduped = new Counter({
        name: 'ml_image_fetch_consumer_deduped_total',
        help: 'URLs skipped as already known, by the layer that caught them: "batch" (another copy in the same poll batch) or "store" (a durable crawl-history result)',
        labelNames: ['scope'],
    })
    /**
     * A sustained rate means the producer and consumer disagree about the wire format.
     */
    private static readonly dropped = new Counter({
        name: 'ml_image_fetch_consumer_dropped_total',
        help: 'URLs refused before dedup because the versioned record, URL, ref, or registrable-domain key was invalid. When a dead-letter topic is configured, its Kafka acknowledgement precedes this increment and the source commit',
        labelNames: ['reason'],
    })
    private static readonly deadLettered = new Counter({
        name: 'ml_image_fetch_consumer_dead_lettered_total',
        help: 'Rejected frontier records acknowledged by the dead-letter topic before the source offset can advance',
        labelNames: ['reason'],
    })
    private static readonly deadLetterFailed = new Counter({
        name: 'ml_image_fetch_consumer_dead_letter_failed_total',
        help: 'Rejected frontier records that could not reach the dead-letter topic. The source batch fails so its offsets remain uncommitted',
        labelNames: ['reason'],
    })
    /**
     * This distribution shows how much independent origin state one poll can activate.
     */
    private static readonly originsPerBatch = new Histogram({
        name: 'ml_image_fetch_consumer_origins_per_batch',
        help: 'Distinct origins in one poll batch',
        buckets: [1, 2, 4, 8, 16, 32, 64],
    })
    private static readonly distinctOriginsPerBatch = new Histogram({
        name: 'ml_image_fetch_consumer_distinct_origins_per_batch',
        help: 'Distinct origins in one poll batch, including empty batches and the full configured batch range',
        buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384],
    })
    private static readonly registrableDomainsPerBatch = new Histogram({
        name: 'ml_image_fetch_consumer_registrable_domains_per_batch',
        help: 'Distinct registrable domains in one poll batch',
        buckets: [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384],
    })
    private static readonly batchTopShare = new Histogram({
        name: 'ml_image_fetch_batch_top_share',
        help: 'Share of deduplicated canonical URL jobs held by the largest fixed number of origins or registrable domains in one poll batch',
        labelNames: ['scope', 'top_n'],
        buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1],
    })
    private static readonly batchEffectiveCount = new Histogram({
        name: 'ml_image_fetch_batch_effective_count',
        help: 'Inverse Simpson effective count of origins or registrable domains among deduplicated canonical URL jobs in one poll batch',
        labelNames: ['scope'],
        buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384, 32_768, 65_536],
    })
    private static readonly partitionRecords = new Counter({
        name: 'ml_image_fetch_partition_records_total',
        help: 'Valid Kafka records handled by source partition',
        labelNames: ['partition'],
    })
    private static readonly partitionUrls = new Counter({
        name: 'ml_image_fetch_partition_urls_total',
        help: 'URL jobs attributed to a source partition and bounded processing stage. A shared deduplicated job counts once for each contributing partition',
        labelNames: ['partition', 'stage'],
    })
    private static readonly partitionTopShare = new Histogram({
        name: 'ml_image_fetch_partition_top_share',
        help: 'Share of deduplicated URL jobs in one source partition held by its largest origin or registrable domain in a joined batch',
        labelNames: ['partition', 'scope'],
        buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1],
    })
    private static readonly partitionEffectiveCount = new Histogram({
        name: 'ml_image_fetch_partition_effective_count',
        help: 'Inverse Simpson effective count of origins or registrable domains for one source partition in a joined batch',
        labelNames: ['partition', 'scope'],
        buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384],
    })
    private static readonly urlsPerRecord = new Histogram({
        name: 'ml_image_fetch_consumer_urls_per_record',
        help: 'URLs carried by one Kafka record. The producer packs a record to a byte budget, so a distribution pinned at the top means the count bound rather than the byte budget is what split it',
        buckets: [1, 8, 32, 64, 128, 256, 512],
    })
    private static readonly storeErrors = new Counter({
        name: 'ml_image_fetch_consumer_store_errors_total',
        help: 'Crawl-history keys in a failed read or write. Either failure stops the batch before Kafka offsets advance',
        labelNames: ['operation'],
    })
    private static readonly storeDuration = new Histogram({
        name: 'ml_image_fetch_consumer_store_duration_seconds',
        help: 'Crawl-history operation wall time by bounded operation and outcome',
        labelNames: ['operation', 'outcome'],
        buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120],
    })
    private static readonly batchDuration = new Histogram({
        name: 'ml_image_fetch_consumer_batch_duration_seconds',
        help: 'Wall time per completed poll batch. Read against Kafka max.poll.interval.ms (300s)',
        buckets: [0.01, 0.05, 0.1, 0.5, 1, 5, 15, 30, 60, 120, 240, 300, 600],
    })
    private static readonly activeBatchStartedAtMs = new Map<symbol, number>()
    private static readonly activeBatchElapsed = new Gauge({
        name: 'ml_image_fetch_consumer_active_batch_elapsed_seconds',
        help: 'Elapsed wall time of the active non-empty poll batch, or zero between batches. This exposes a stuck batch before Kafka max.poll.interval.ms revokes it',
        collect() {
            const startedAtMs =
                ImageFetchConsumerMetrics.activeBatchStartedAtMs.size > 0
                    ? Math.min(...ImageFetchConsumerMetrics.activeBatchStartedAtMs.values())
                    : undefined
            this.set(startedAtMs === undefined ? 0 : Math.max(0, performance.now() - startedAtMs) / 1000)
        },
    })
    private static readonly ageSeconds = new Histogram({
        name: 'ml_image_fetch_consumer_url_age_seconds',
        help: 'Age of a URL when this lane reached it, measured from capture rather than from produce. The tail shows the age of the backlog',
        buckets: [1, 10, 60, 300, 900, 3600, 6 * 3600, 24 * 3600],
    })
    private static readonly dryRun = new Gauge({
        name: 'ml_image_fetch_consumer_dry_run',
        help: '1 while the lane sends no outbound request, 0 once fetching is enabled. Every other metric of this lane means something different either side of this value',
    })

    public static setDryRun(enabled: boolean): void {
        this.dryRun.set(enabled ? 1 : 0)
    }
    public static incFetchable(count: number): void {
        this.fetchable.inc(count)
    }
    public static incDeduped(scope: DedupScope, count: number): void {
        this.deduped.labels(scope).inc(count)
    }
    public static incDropped(reason: UrlDropReason, count: number): void {
        this.dropped.labels(reason).inc(count)
    }
    public static incDeadLettered(reason: FrontierDeadLetterReason): void {
        this.deadLettered.labels(reason).inc()
    }
    public static incDeadLetterFailed(reason: FrontierDeadLetterReason): void {
        this.deadLetterFailed.labels(reason).inc()
    }
    public static incStoreError(operation: 'read' | 'write', count: number): void {
        this.storeErrors.labels(operation).inc(count)
    }
    public static observeStoreDuration(
        operation: 'read' | 'write',
        outcome: 'success' | 'error',
        durationSeconds: number
    ): void {
        this.storeDuration.labels(operation, outcome).observe(durationSeconds)
    }
    public static observeBatch(origins: number, registrableDomains: number, durationSeconds: number): void {
        this.originsPerBatch.observe(origins)
        this.distinctOriginsPerBatch.observe(origins)
        this.registrableDomainsPerBatch.observe(registrableDomains)
        this.batchDuration.observe(durationSeconds)
    }
    public static observeBatchDiversity(originCounts: number[], registrableDomainCounts: number[]): void {
        this.observeBatchDistribution('origin', originCounts)
        this.observeBatchDistribution('registrable_domain', registrableDomainCounts)
    }
    public static startBatch(nowMs = performance.now()): symbol {
        const batchId = Symbol()
        this.activeBatchStartedAtMs.set(batchId, nowMs)
        return batchId
    }
    public static finishBatch(batchId: symbol): void {
        this.activeBatchStartedAtMs.delete(batchId)
    }
    public static observeRecord(urls: number): void {
        this.urlsPerRecord.observe(urls)
    }
    public static observePartitionRecord(partition: number, urls: number, acceptedUrls: number): void {
        const partitionLabel = String(partition)
        this.partitionRecords.labels(partitionLabel).inc()
        this.partitionUrls.labels(partitionLabel, 'parsed').inc(urls)
        this.partitionUrls.labels(partitionLabel, 'accepted').inc(acceptedUrls)
    }
    public static incPartitionUrls(partition: number, stage: PartitionUrlStage, count: number): void {
        this.partitionUrls.labels(String(partition), stage).inc(count)
    }
    public static observePartitionBatchDiversity(
        partition: number,
        originCounts: number[],
        registrableDomainCounts: number[]
    ): void {
        this.observePartitionDistribution(partition, 'origin', originCounts)
        this.observePartitionDistribution(partition, 'registrable_domain', registrableDomainCounts)
    }
    public static observeAge(ageSeconds: number): void {
        this.ageSeconds.observe(ageSeconds)
    }

    private static observeBatchDistribution(scope: BatchDiversityScope, counts: number[]): void {
        const summary = summarizeBatchDistribution(counts)
        if (!summary) {
            return
        }
        for (const topCount of BATCH_DIVERSITY_TOP_COUNTS) {
            const topTotal = summary.largestCounts.slice(0, topCount).reduce((total, count) => total + count, 0)
            this.batchTopShare.labels(scope, String(topCount)).observe(topTotal / summary.total)
        }
        this.batchEffectiveCount.labels(scope).observe((summary.total * summary.total) / summary.sumOfSquares)
    }

    private static observePartitionDistribution(partition: number, scope: BatchDiversityScope, counts: number[]): void {
        const summary = summarizeBatchDistribution(counts)
        if (!summary) {
            return
        }
        const partitionLabel = String(partition)
        this.partitionTopShare.labels(partitionLabel, scope).observe(summary.largestCounts[0] / summary.total)
        this.partitionEffectiveCount
            .labels(partitionLabel, scope)
            .observe((summary.total * summary.total) / summary.sumOfSquares)
    }
}

function summarizeBatchDistribution(
    counts: number[]
): { total: number; sumOfSquares: number; largestCounts: number[] } | undefined {
    let total = 0
    let sumOfSquares = 0
    const largestCounts: number[] = []
    for (const count of counts) {
        total += count
        sumOfSquares += count * count
        const insertionIndex = largestCounts.findIndex((existing) => count > existing)
        if (insertionIndex >= 0) {
            largestCounts.splice(insertionIndex, 0, count)
        } else if (largestCounts.length < BATCH_DIVERSITY_TOP_COUNTS.at(-1)!) {
            largestCounts.push(count)
        }
        if (largestCounts.length > BATCH_DIVERSITY_TOP_COUNTS.at(-1)!) {
            largestCounts.pop()
        }
    }
    return total > 0 ? { total, sumOfSquares, largestCounts } : undefined
}

/**
 * The request path.
 *
 * No metric here carries a host or a URL. The host set is unbounded, so it lives in the structured
 * logs of the runner. A URL is page content and belongs in no metric, log, or trace.
 */
export class ImageFetchRequestMetrics {
    private static readonly completedUrls = new Counter({
        name: 'ml_image_fetch_completed_urls_total',
        help: 'Completed URLs by final outcome and refusal reason',
        labelNames: ['outcome', 'refusal_reason'],
    })
    private static readonly completedUrlSystemTime = new Histogram({
        name: 'ml_image_fetch_completed_url_system_time_seconds',
        help: 'Time from first collection until the URL reaches a terminal outcome',
        buckets: [1, 60, 600, 3600, 6 * 3600, 24 * 3600, 7 * 24 * 3600, 30 * 24 * 3600],
    })
    private static readonly completedUrlFetches = new Histogram({
        name: 'ml_image_fetch_completed_url_fetches',
        help: 'Image HTTP requests made before a URL reaches a terminal outcome',
        buckets: [0, 1, 2, 3, 5, 10],
    })
    private static readonly completedUrlRepublishes = new Histogram({
        name: 'ml_image_fetch_completed_url_republishes',
        help: 'Frontier and delay-topic republishes before a URL reaches a terminal outcome',
        buckets: [0, 1, 2, 3, 5, 10],
    })
    private static readonly policyAndBudgetDecisions = new Counter({
        name: 'ml_image_fetch_policy_and_budget_decisions_total',
        help: 'Origin-policy and registrable-domain request-control decisions after block state is known',
        labelNames: ['blocked', 'reason'],
    })
    private static readonly batchSchedulableSlots = new Histogram({
        name: 'ml_image_fetch_batch_schedulable_slots',
        help: 'Request slots that the initial fetch queue can use after live pod and registrable-domain concurrency limits',
        buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 512, 1024],
    })
    private static readonly batchSchedulableCapacityRatio = new Histogram({
        name: 'ml_image_fetch_batch_schedulable_capacity_ratio',
        help: 'Share of the pod request limit that the initial fetch queue can use after live concurrency limits',
        buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1],
    })
    /**
     * `ok` against the sum is the yield of the lane.
     */
    private static readonly outcomes = new Counter({
        name: 'ml_image_fetch_requests_total',
        help: 'Completed external HTTP requests by status class or network failure',
        labelNames: ['outcome'],
    })
    private static readonly duration = new Histogram({
        name: 'ml_image_fetch_request_duration_seconds',
        help: 'Time for one completed external HTTP request, including its response body',
        labelNames: ['outcome'],
        buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
    })
    private static readonly partitionOutcomes = new Counter({
        name: 'ml_image_fetch_partition_requests_total',
        help: 'Completed image HTTP requests attributed to each source partition and status class or network failure',
        labelNames: ['partition', 'outcome'],
    })
    private static readonly partitionDuration = new Histogram({
        name: 'ml_image_fetch_partition_request_duration_seconds',
        help: 'Time for one completed image HTTP request attributed to each source partition, including its response body',
        labelNames: ['partition', 'outcome'],
        buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
    })
    private static readonly partitionAttempts = new Counter({
        name: 'ml_image_fetch_partition_attempts_total',
        help: 'URL jobs completed or republished after successful delivery and URL accounting, attributed to each source partition and outcome',
        labelNames: ['partition', 'disposition', 'outcome'],
    })
    private static readonly retryCauses = new Counter({
        name: 'ml_image_fetch_retry_causes_total',
        help: 'Transient fetch outcomes that caused the URL to be scheduled for another attempt',
        labelNames: ['cause'],
    })
    /**
     * Read a rising tail with the `deadline` outcome to distinguish headroom from load that an
     * origin's allowed rate cannot carry within one pass.
     */
    private static readonly schedulerWait = new Histogram({
        name: 'ml_image_fetch_scheduler_wait_seconds',
        help: 'Time a request waited for an origin crawl delay, registrable-domain rate, or pod request slot',
        labelNames: ['scope'],
        buckets: [0, 0.1, 0.5, 1, 2, 5, 10, 20],
    })
    private static readonly partitionSchedulerWait = new Histogram({
        name: 'ml_image_fetch_partition_scheduler_wait_seconds',
        help: 'Time an image request waited, attributed to each source partition and politeness or capacity scope',
        labelNames: ['partition', 'scope'],
        buckets: [0, 0.1, 0.5, 1, 2, 5, 10, 20],
    })
    private static readonly responseBytes = new Histogram({
        name: 'ml_image_fetch_response_bytes',
        help: 'Size of a downloaded image. The tail against the configured byte limit says how much of the catalog the limit refuses',
        buckets: [
            1024,
            8 * 1024,
            32 * 1024,
            128 * 1024,
            512 * 1024,
            1024 * 1024,
            2 * 1024 * 1024,
            10 * 1024 * 1024,
            20 * 1024 * 1024,
        ],
    })
    private static readonly redirects = new Histogram({
        name: 'ml_image_fetch_redirects',
        help: 'Redirects followed for one URL. Each hop uses its registrable-domain budget and origin crawl delay',
        buckets: [0, 1, 2, 3],
    })
    /**
     * Both gauges read the budget at scrape time. A hold expires by the clock, so a count taken at
     * the end of a batch would report blocked origins until the next batch arrives.
     */
    private static readonly trackedRegistrableDomains = new Gauge({
        name: 'ml_image_fetch_tracked_registrable_domains',
        help: 'Registrable domains this pod holds request-control state for',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.trackedRegistrableDomains ?? 0)
        },
    })
    private static readonly trackedOrigins = new Gauge({
        name: 'ml_image_fetch_tracked_origins',
        help: 'Origins this pod holds configuration and crawl-delay state for',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.trackedOrigins ?? 0)
        },
    })
    private static readonly blockedRegistrableDomains = new Gauge({
        name: 'ml_image_fetch_blocked_registrable_domains',
        help: 'Registrable domains held by transient back-off, Retry-After, or an open circuit breaker',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.blockedRegistrableDomains(Date.now()) ?? 0)
        },
    })

    public static outcomeForHttpStatus(status?: number): HttpRequestOutcome {
        if (status === undefined) {
            return 'network_error'
        }
        if (status >= 200 && status < 300) {
            return '2xx'
        }
        if (status >= 300 && status < 400) {
            return '3xx'
        }
        if (status >= 400 && status < 500) {
            return '4xx'
        }
        if (status >= 500 && status < 600) {
            return '5xx'
        }
        return 'other'
    }
    public static observeRequest(
        outcome: HttpRequestOutcome,
        durationSeconds: number,
        sourcePartitions?: readonly number[]
    ): void {
        this.outcomes.labels(outcome).inc()
        this.duration.labels(outcome).observe(durationSeconds)
        for (const sourcePartition of new Set(sourcePartitions ?? [])) {
            const partitionLabel = String(sourcePartition)
            this.partitionOutcomes.labels(partitionLabel, outcome).inc()
            this.partitionDuration.labels(partitionLabel, outcome).observe(durationSeconds)
        }
    }
    public static incRetryCause(cause: TransientFetchOutcome): void {
        this.retryCauses.labels(cause).inc()
    }
    public static observeRedirectCount(redirects: number): void {
        this.redirects.observe(redirects)
    }
    public static observeCompletedUrl(
        outcome: AttemptOutcome,
        refusalReason: FetchRefusalReason | 'none',
        systemTimeSeconds: number,
        fetches: number,
        republishes: number
    ): void {
        this.completedUrls.labels(outcome, refusalReason).inc()
        this.completedUrlSystemTime.observe(systemTimeSeconds)
        this.completedUrlFetches.observe(fetches)
        this.completedUrlRepublishes.observe(republishes)
    }
    public static observePolicyAndBudgetDecision(blocked: boolean, reason: PolicyAndBudgetReason = 'none'): void {
        this.policyAndBudgetDecisions.labels(blocked ? 'true' : 'false', reason).inc()
    }
    public static observeBatchSchedulableCapacity(slots: number, podRequestLimit: number): void {
        const boundedSlots = Math.min(slots, podRequestLimit)
        this.batchSchedulableSlots.observe(boundedSlots)
        this.batchSchedulableCapacityRatio.observe(boundedSlots / podRequestLimit)
    }
    public static observeSchedulerWait(
        scope: SchedulerWaitScope,
        waitSeconds: number,
        sourcePartitions?: readonly number[]
    ): void {
        this.schedulerWait.labels(scope).observe(waitSeconds)
        for (const sourcePartition of new Set(sourcePartitions ?? [])) {
            this.partitionSchedulerWait.labels(String(sourcePartition), scope).observe(waitSeconds)
        }
    }
    public static incPartitionAttempt(
        partition: number,
        disposition: PartitionAttemptDisposition,
        outcome: AttemptOutcome
    ): void {
        this.partitionAttempts.labels(String(partition), disposition, outcome).inc()
    }
    public static observeBytes(bytes: number): void {
        this.responseBytes.observe(bytes)
    }
    private static readonly evictedWhileBlocked = new Gauge({
        name: 'ml_image_fetch_registrable_domains_evicted_while_blocked',
        help: 'Registrable domains removed from request-control state while still blocked. This must stay zero',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.evictedWhileBlocked ?? 0)
        },
    })

    /**
     * Requests holding a socket right now, against the pod limit.
     *
     * A request waiting for a politeness token has not reached this yet, so a value at the limit
     * means the pod is the bottleneck rather than the sites.
     */
    private static readonly inFlight = new Gauge({
        name: 'ml_image_fetch_requests_in_flight',
        help: 'External requests this pod holds open. A URL waiting for its registrable-domain rate limit holds no socket and is not counted',
        collect() {
            this.set(ImageFetchRequestMetrics.requests?.running ?? 0)
        },
    })

    private static budget: BudgetCounts | undefined
    private static requests: InFlightCount | undefined

    /** The runner owns both. */
    public static trackBudget(budget: BudgetCounts, requests: InFlightCount): void {
        this.budget = budget
        this.requests = requests
    }

    /**
     * Read against `ml_image_fetch_requests_total` this is the amplification factor, because the lane
     * reads every republished message again. A rate that approaches the request rate means most work
     * goes around rather than completes.
     */
    private static readonly republished = new Counter({
        name: 'ml_image_fetch_republished_total',
        help: 'URLs published back to Kafka by bounded reason and destination class. "redirect" left the origin. "retry" hit a transient failure and waits in a delay topic. "not_ready" arrived before its wait ended',
        labelNames: ['reason', 'topic'],
    })
    private static readonly republishFailed = new Counter({
        name: 'ml_image_fetch_republish_failed_total',
        help: 'URLs in a Kafka message whose republish delivery failed. The input batch throws and leaves its offsets uncommitted',
        labelNames: ['reason'],
    })
    private static readonly republishMessagesPerBatch = new Histogram({
        name: 'ml_image_fetch_republish_messages_per_batch',
        help: 'Kafka record delivery attempts by one fetch batch for each destination topic class',
        labelNames: ['topic'],
        buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384],
    })
    private static readonly republishRegistrableDomainsPerBatch = new Histogram({
        name: 'ml_image_fetch_republish_registrable_domains_per_batch',
        help: 'Distinct registrable-domain keys in delivery attempts by one fetch batch for each destination topic class',
        labelNames: ['topic'],
        buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16_384],
    })
    private static readonly republishDuration = new Histogram({
        name: 'ml_image_fetch_republish_duration_seconds',
        help: 'Wall time from scheduling one destination topic class until all its started Kafka delivery attempts settle',
        labelNames: ['topic'],
        buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 240, 300],
    })
    private static readonly republishFlushDuration = new Histogram({
        name: 'ml_image_fetch_republish_flush_duration_seconds',
        help: 'Total wall time to group, serialize, and wait for every started republish delivery in one fetch batch',
        buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 240, 300],
    })
    private static readonly republishFlushDeadlineExceeded = new Counter({
        name: 'ml_image_fetch_republish_flush_deadline_exceeded_total',
        help: 'Fetch batches that stopped starting Kafka republish records to preserve final history-write and poll-interval margin',
    })
    /**
     * Zero is the common case. The tail shows redirect chains and retries.
     */
    private static readonly hopsUsed = new Histogram({
        name: 'ml_image_fetch_hops_used',
        help: 'Redirects and retries spent from one URL job before the lane finished it',
        buckets: [0, 1, 2, 3, 5, 10],
    })

    public static incRepublished(reason: RepublishReason, destination: RepublishDestination): void {
        this.republished.labels(reason, destination).inc()
    }
    public static incRepublishFailed(reason: RepublishReason): void {
        this.republishFailed.labels(reason).inc()
    }
    public static observeRepublishBatch(
        topic: RepublishTopic,
        messages: number,
        registrableDomains: number,
        durationSeconds: number
    ): void {
        this.republishMessagesPerBatch.labels(topic).observe(messages)
        this.republishRegistrableDomainsPerBatch.labels(topic).observe(registrableDomains)
        this.republishDuration.labels(topic).observe(durationSeconds)
    }
    public static observeRepublishFlush(durationSeconds: number): void {
        this.republishFlushDuration.observe(durationSeconds)
    }
    public static incRepublishFlushDeadlineExceeded(): void {
        this.republishFlushDeadlineExceeded.inc()
    }
    public static observeHops(hops: number): void {
        this.hopsUsed.observe(hops)
    }
}

/**
 * The consumer of one delay topic.
 *
 * Lag on these topics is the design at work rather than a fault, because a record that waits out its
 * period counts as lag. Read `ml_image_fetch_retry_wait_seconds` against the period of the topic
 * instead. A wait far short of the period means records arrive with their wait already spent, which
 * means the tier below is too small.
 */
export class RetryDelayMetrics {
    private static readonly released = new Counter({
        name: 'ml_image_fetch_retry_released_total',
        help: 'Records this delay consumer handled by outcome. A malformed record is dropped, while an invalid timestamp or failed publish leaves the offset uncommitted',
        labelNames: ['outcome'],
    })
    private static readonly waitSeconds = new Histogram({
        name: 'ml_image_fetch_retry_wait_seconds',
        help: 'Time a record still had to wait when this consumer read it. Compare with the period of the topic: a much shorter wait means the records arrived late, and the consumer is behind',
        buckets: [1, 10, 60, 300, 600, 1800, 3600],
    })

    public static incReleased(
        outcome: 'released' | 'failed' | 'malformed' | 'invalid_timestamp' | 'abandoned',
        count = 1
    ): void {
        this.released.labels(outcome).inc(count)
    }
    public static observeWait(waitSeconds: number): void {
        this.waitSeconds.observe(waitSeconds)
    }
}
