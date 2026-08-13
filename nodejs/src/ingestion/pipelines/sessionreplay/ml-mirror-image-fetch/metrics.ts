import { Counter, Gauge, Histogram } from 'prom-client'

export type UrlDropReason =
    | 'malformed'
    | 'unsupported_version'
    | 'stale'
    | 'bad_ref'
    | 'bad_url'
    | 'foreign_domain'
    | 'oversized_record'
    | 'too_early'

export type DedupScope = 'batch' | 'pod' | 'store'

export class ImageFetchConsumerMetrics {
    /**
     * URLs that reached the end of the dry run, meaning the lane would have sent a request for them.
     *
     * This is the phase 0 headline. Divided by the window it gives the request rate the fetcher would
     * offer, which is the number that decides whether the politeness budget of section 4.5 can carry
     * real traffic.
     */
    private static readonly fetchable = new Counter({
        name: 'ml_image_fetch_consumer_fetchable_total',
        help: 'URLs that passed every check and would have been fetched. In dry run no request is sent, so this is the offered rate rather than the sent rate',
    })
    /**
     * Duplicates split by which layer caught them.
     *
     * The split is the measurement, not the total. `batch` and `pod` are free and bounded by memory,
     * `store` costs a Redis read, and anything the store catches that the pod cache did not is what
     * the shared store is buying. A high `store` share against a full pod cache says the cache is
     * undersized; a low one says it is already holding the working set.
     */
    private static readonly deduped = new Counter({
        name: 'ml_image_fetch_consumer_deduped_total',
        help: 'URLs skipped as already known, by the layer that caught them: "batch" (another copy in the same poll batch), "pod" (this pod saw it earlier), "store" (another pod saw it, or this pod before a restart)',
        labelNames: ['scope'],
    })
    /**
     * URLs the lane refused before any dedup decision.
     *
     * `stale` is the expected one under a backlog and is working as designed. The others mean the
     * producer and this consumer disagree about the wire format, so a sustained rate on any of them
     * zeroes the lane while looking healthy from the Kafka side.
     */
    private static readonly dropped = new Counter({
        name: 'ml_image_fetch_consumer_dropped_total',
        help: 'URLs refused before dedup, by reason: "stale" (older than the age limit), "malformed" / "unsupported_version" / "oversized_record" (the record did not parse), "bad_ref" / "bad_url" (an entry inside a record did not parse), "foreign_domain" (the host sits outside the domain the record is keyed by), "too_early" (it is still waiting out a retry delay)',
        labelNames: ['reason'],
    })
    /**
     * Distinct registrable domains seen per poll batch.
     *
     * The topic is keyed by domain, so one partition carries a small number of domains and one pod
     * holds their whole request rate. A batch spanning many domains means the key is spreading work
     * more finely than the partition count can express, which is what would let one pod exceed a
     * single site's budget.
     */
    private static readonly domainsPerBatch = new Histogram({
        name: 'ml_image_fetch_consumer_domains_per_batch',
        help: 'Distinct registrable domains in one poll batch. The politeness budget is per domain and held by the pod owning the partition, so this bounds how many budgets one pod runs at once',
        buckets: [1, 2, 4, 8, 16, 32, 64],
    })
    private static readonly urlsPerRecord = new Histogram({
        name: 'ml_image_fetch_consumer_urls_per_record',
        help: 'URLs carried by one Kafka record. The producer packs a record to a byte budget, so a distribution pinned at the top means the count bound rather than the byte budget is what split it',
        buckets: [1, 8, 32, 64, 128, 256, 512],
    })
    private static readonly storeErrors = new Counter({
        name: 'ml_image_fetch_consumer_store_errors_total',
        help: 'Crawl-history keys that failed, by operation. A failed read makes the lane treat a known URL as new, so the measured hit rate understates the real one. A failed write leaves the URL unrecorded, so the next pod to see it counts it again',
        labelNames: ['operation'],
    })
    private static readonly batchDuration = new Histogram({
        name: 'ml_image_fetch_consumer_batch_duration_seconds',
        help: 'Wall time per poll batch. Read against CONSUMER_MAX_HEARTBEAT_INTERVAL_MS (30s), which binds long before max.poll.interval.ms: the batch refreshes the heartbeat from inside itself, so a batch past this means that refresh stopped',
        buckets: [0.01, 0.05, 0.1, 0.5, 1, 5, 15, 30, 60],
    })
    private static readonly ageSeconds = new Histogram({
        name: 'ml_image_fetch_consumer_url_age_seconds',
        help: 'Age of a URL when this lane reached it, measured from capture rather than from produce. The tail against the configured age limit says how much of a backlog would be dropped rather than fetched',
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
    public static incStoreError(operation: 'read' | 'write', count: number): void {
        this.storeErrors.labels(operation).inc(count)
    }
    public static observeBatch(domains: number, durationSeconds: number): void {
        this.domainsPerBatch.observe(domains)
        this.batchDuration.observe(durationSeconds)
    }
    public static observeRecord(urls: number): void {
        this.urlsPerRecord.observe(urls)
    }
    public static observeAge(ageSeconds: number): void {
        this.ageSeconds.observe(ageSeconds)
    }
}

/**
 * The request path.
 *
 * No metric here carries a host or a URL. The host set is unbounded, so it lives in the structured
 * logs of the runner; a URL is page content and belongs in no metric, log, or trace.
 */
export class ImageFetchRequestMetrics {
    /**
     * Every URL that left the dedup stage, by what happened to it.
     *
     * `ok` against the sum is the yield of the lane. The site answers `not_found`, `forbidden`,
     * `rate_limited`, and `server_error`. This lane refuses `too_large`, `not_image`, `blocked`,
     * `bad_redirect`, and `too_many_redirects`. The budget never sends `breaker_open` or `deadline`,
     * and those are the only ones a later batch offers again.
     */
    private static readonly outcomes = new Counter({
        name: 'ml_image_fetch_requests_total',
        help: 'URLs that reached the request stage, by outcome. "deadline" and "breaker_open" were never sent, so they are the lane asking for more pods or a slower site, not a failure of the fetch itself',
        labelNames: ['outcome'],
    })
    private static readonly duration = new Histogram({
        name: 'ml_image_fetch_request_duration_seconds',
        help: 'Time from the first request of a URL to its outcome, redirects included. It excludes the wait for a rate-limit token, which ml_image_fetch_budget_wait_seconds holds',
        labelNames: ['outcome'],
        buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
    })
    /**
     * What politeness costs in latency.
     *
     * A rising tail means one domain is offering more URLs than its rate carries. Past the batch
     * budget the wait becomes a `deadline` shed, so read this against that outcome. A growing wait
     * with no sheds is headroom. A growing wait with sheds is a domain the lane cannot keep up with.
     */
    private static readonly budgetWait = new Histogram({
        name: 'ml_image_fetch_budget_wait_seconds',
        help: 'Time a URL waited for its domain rate limit before its request went out',
        buckets: [0, 0.1, 0.5, 1, 2, 5, 10, 20],
    })
    private static readonly responseBytes = new Histogram({
        name: 'ml_image_fetch_response_bytes',
        help: 'Size of a downloaded image. The tail against the configured byte limit says how much of the catalog the limit refuses',
        buckets: [1024, 8 * 1024, 32 * 1024, 128 * 1024, 512 * 1024, 1024 * 1024, 2 * 1024 * 1024],
    })
    private static readonly redirects = new Histogram({
        name: 'ml_image_fetch_redirects',
        help: 'Redirects followed for one URL. Each hop is a separate request against the budget of whichever domain it lands on',
        buckets: [0, 1, 2, 3],
    })
    /**
     * Domains this pod holds a budget for, and how many of those it may not send to.
     *
     * The tracked count against the configured maximum says whether the map is evicting, and an
     * eviction forgets that a domain is blocked. The blocked count is how many sites this lane is
     * currently leaving alone.
     */
    private static readonly trackedDomains = new Gauge({
        name: 'ml_image_fetch_tracked_domains',
        help: 'Registrable domains this pod holds rate-limit state for',
    })
    private static readonly blockedDomains = new Gauge({
        name: 'ml_image_fetch_blocked_domains',
        help: 'Domains this pod is currently sending nothing to, because a breaker opened or a Retry-After header is still in force',
    })

    public static incOutcome(outcome: string): void {
        this.outcomes.labels(outcome).inc()
    }
    public static observeRequest(outcome: string, durationSeconds: number, redirects: number): void {
        this.outcomes.labels(outcome).inc()
        this.duration.labels(outcome).observe(durationSeconds)
        this.redirects.observe(redirects)
    }
    public static observeBudgetWait(waitSeconds: number): void {
        this.budgetWait.observe(waitSeconds)
    }
    public static observeBytes(bytes: number): void {
        this.responseBytes.observe(bytes)
    }
    private static readonly evictedWhileBlocked = new Gauge({
        name: 'ml_image_fetch_domains_evicted_while_blocked',
        help: 'Domains dropped from the rate-limit map while they were still blocked. Each one resumes traffic to a site that asked us to wait, so a rising value means the tracked-domain limit is too low',
    })

    /**
     * URLs put back into the frontier rather than finished with.
     *
     * Read against `ml_image_fetch_requests_total` this is the amplification factor: every republish
     * is a message the lane will read again. A rate approaching the request rate means most work is
     * going around rather than completing. Requirement 27.
     */
    private static readonly republished = new Counter({
        name: 'ml_image_fetch_republished_total',
        help: 'URLs published back to Kafka, by why and to which topic. "redirect" left the registrable domain, so another consumer owns its budget. "retry" hit a transient failure and waits in a delay topic',
        labelNames: ['reason', 'topic'],
    })
    private static readonly republishFailed = new Counter({
        name: 'ml_image_fetch_republish_failed_total',
        help: 'URLs that could not be put back. Each one is dropped without a crawl history entry, so it returns only when a session refers to it again',
        labelNames: ['reason'],
    })
    /**
     * Moves a URL made before it finished.
     *
     * Zero is the common case: fetched on first sight. The tail shows redirect chains and retries,
     * and anything at the budget is a URL the lane gave up on. Requirement 26.
     */
    private static readonly hopsUsed = new Histogram({
        name: 'ml_image_fetch_hops_used',
        help: 'Moves one URL made before the lane finished with it. A redirect, a republish, and a retry each count one',
        buckets: [0, 1, 2, 3, 5, 10],
    })

    public static incRepublished(reason: string, topic: string): void {
        this.republished.labels(reason, topic).inc()
    }
    public static incRepublishFailed(reason: string): void {
        this.republishFailed.labels(reason).inc()
    }
    public static observeHops(hops: number): void {
        this.hopsUsed.observe(hops)
    }
    public static observeBudget(tracked: number, blocked: number, evictedWhileBlocked: number): void {
        this.trackedDomains.set(tracked)
        this.blockedDomains.set(blocked)
        this.evictedWhileBlocked.set(evictedWhileBlocked)
    }
}

/**
 * The consumer of one delay topic.
 *
 * Lag on these topics is the design working rather than a fault: a record waiting out its period is
 * lag. Read `ml_image_fetch_retry_wait_seconds` against the period of the topic instead. A wait far
 * short of the period means records are arriving already ripe, which means the tier below is too
 * small.
 */
export class RetryDelayMetrics {
    private static readonly released = new Counter({
        name: 'ml_image_fetch_retry_released_total',
        help: 'Records this delay consumer finished with, by what happened: "released" back to the frontier, "failed" to publish, or "malformed" and dropped',
        labelNames: ['outcome'],
    })
    private static readonly waitSeconds = new Histogram({
        name: 'ml_image_fetch_retry_wait_seconds',
        help: 'Time a record still had to wait when this consumer read it. Compare with the period of the topic: a much shorter wait means the records arrived late, and the consumer is behind',
        buckets: [1, 10, 60, 300, 600, 1800, 3600],
    })

    public static incReleased(outcome: 'released' | 'failed' | 'malformed'): void {
        this.released.labels(outcome).inc()
    }
    public static observeWait(waitSeconds: number): void {
        this.waitSeconds.observe(waitSeconds)
    }
}
