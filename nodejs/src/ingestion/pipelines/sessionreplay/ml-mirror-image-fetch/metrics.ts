import { Counter, Gauge, Histogram } from 'prom-client'

import type { TeamVolume } from './team-volume'

/** What the in-flight gauge reads. Narrower than `ConcurrencyController`, so the metrics do not depend on the whole of it. */
export interface InFlightCount {
    readonly running: number
}

/** What the budget gauges read. Narrower than `HostBudget`, so the metrics do not depend on the whole of it. */
export interface BudgetCounts {
    readonly trackedDomains: number
    readonly evictedWhileBlocked: number
    blockedDomains(nowMs: number): number
}

export type UrlDropReason =
    | 'malformed'
    | 'unsupported_version'
    | 'stale'
    | 'bad_ref'
    | 'bad_url'
    | 'foreign_domain'
    | 'private_host'
    | 'oversized_record'

export type DedupScope = 'batch' | 'pod' | 'store'

export class ImageFetchConsumerMetrics {
    private static readonly fetchable = new Counter({
        name: 'ml_image_fetch_consumer_fetchable_total',
        help: 'URLs that passed every check and would have been fetched. In dry run no request is sent, so this is the offered rate rather than the sent rate',
    })
    /**
     * `batch` and `pod` cost only memory, and `store` costs a shared-store read, so the split is the
     * measurement rather than the total. A high `store` share against a full pod cache says the pod
     * cache is too small. A low one says the pod cache already holds the working set.
     */
    private static readonly deduped = new Counter({
        name: 'ml_image_fetch_consumer_deduped_total',
        help: 'URLs skipped as already known, by the layer that caught them: "batch" (another copy in the same poll batch), "pod" (this pod saw it earlier), "store" (another pod saw it, or this pod before a restart)',
        labelNames: ['scope'],
    })
    /**
     * `stale` is the expected reason under a backlog. The others mean the producer and this consumer
     * disagree about the wire format, so a sustained rate on any of them takes the lane to zero while
     * the Kafka side still looks healthy.
     */
    private static readonly dropped = new Counter({
        name: 'ml_image_fetch_consumer_dropped_total',
        help: 'URLs refused before dedup, by reason: "stale" (older than the age limit), "malformed" / "unsupported_version" / "oversized_record" (the record did not parse), "bad_ref" / "bad_url" (an entry inside a record did not parse), "foreign_domain" (the key is not the registrable domain of the host), "private_host" (the host is a private address or a name that only resolves inside a network)',
        labelNames: ['reason'],
    })
    /**
     * A batch that spans many domains means the key spreads work more finely than the partition count
     * can express, which is what would let one pod pass the budget of a single site.
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
 * logs of the runner. A URL is page content and belongs in no metric, log, or trace.
 */
export class ImageFetchRequestMetrics {
    /**
     * `ok` against the sum is the yield of the lane. The site answers `not_found`, `forbidden`,
     * `rate_limited`, and `server_error`. This lane refuses `too_large`, `not_image`, `blocked`,
     * `bad_redirect`, and `too_many_redirects`. Only `breaker_open` and `deadline` come back in a
     * later batch.
     */
    private static readonly outcomes = new Counter({
        name: 'ml_image_fetch_requests_total',
        help: 'URLs that reached the request stage, by outcome. "deadline", "breaker_open", "connection_limit" and "rate_limited" cover URLs the lane never sent, so they say the lane wants more pods or the site wants less traffic, rather than that a fetch failed',
        labelNames: ['outcome'],
    })
    private static readonly duration = new Histogram({
        name: 'ml_image_fetch_request_duration_seconds',
        help: 'Time from the first request of a URL to its outcome, redirects included. It excludes the wait for a rate-limit token, which ml_image_fetch_budget_wait_seconds holds',
        labelNames: ['outcome'],
        buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
    })
    /**
     * A rising tail means one domain offers more URLs than its rate carries. Past the pass deadline
     * the wait becomes a `deadline` shed, so read this against that outcome: a growing wait with no
     * sheds is headroom, and a growing wait with sheds is a domain the lane cannot keep up with.
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
     * The tracked count against the configured maximum says whether the map evicts, and an eviction
     * forgets that a domain is blocked.
     *
     * Both gauges read the budget at scrape time. A hold expires by the clock, so a count taken at
     * the end of a batch would report blocked domains until the next batch arrives.
     */
    private static readonly trackedDomains = new Gauge({
        name: 'ml_image_fetch_tracked_domains',
        help: 'Registrable domains this pod holds rate-limit state for',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.trackedDomains ?? 0)
        },
    })
    private static readonly blockedDomains = new Gauge({
        name: 'ml_image_fetch_blocked_domains',
        help: 'Domains this pod is currently sending nothing to, because a breaker opened or a Retry-After header is still in force',
        collect() {
            this.set(ImageFetchRequestMetrics.budget?.blockedDomains(Date.now()) ?? 0)
        },
    })

    public static incOutcome(outcome: string, count = 1): void {
        this.outcomes.labels(outcome).inc(count)
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
        help: "Image requests this pod holds open right now. A URL waiting for its domain's rate limit is not counted, because it holds no socket",
        collect() {
            this.set(ImageFetchRequestMetrics.requests?.running ?? 0)
        },
    })

    private static budget: BudgetCounts | undefined
    private static requests: InFlightCount | undefined

    /**
     * URLs a shed left in the back queue, which the lane will not put back.
     *
     * A pass sheds whatever it did not reach, and one back queue can hold far more than a delay
     * tier can carry. Republishing all of them answers overload with more Kafka traffic, and the
     * same URLs come round again a minute later, each having spent a hop.
     */
    private static readonly shedDropped = new Counter({
        name: 'ml_image_fetch_shed_dropped_total',
        help: 'URLs a shed did not put back, because one pass republishes at most a fixed number for one domain. They return when a session refers to the same image',
    })

    public static incShedDropped(count: number): void {
        this.shedDropped.inc(count)
    }

    /** The runner owns both. Requirement 28. */
    public static trackBudget(budget: BudgetCounts, requests: InFlightCount): void {
        this.budget = budget
        this.requests = requests
    }

    /**
     * Read against `ml_image_fetch_requests_total` this is the amplification factor, because the lane
     * reads every republished message again. A rate that approaches the request rate means most work
     * goes around rather than completes. Requirement 27.
     */
    private static readonly republished = new Counter({
        name: 'ml_image_fetch_republished_total',
        help: 'URLs published back to Kafka, by why and to which topic. "redirect" left the registrable domain, so another consumer owns its budget. "retry" hit a transient failure and waits in a delay topic. "not_ready" arrived before the period it was waiting out had passed',
        labelNames: ['reason', 'topic'],
    })
    private static readonly republishFailed = new Counter({
        name: 'ml_image_fetch_republish_failed_total',
        help: 'URLs that could not be put back. Each one is dropped without a crawl history entry, so it returns only when a session refers to it again',
        labelNames: ['reason'],
    })
    /**
     * Zero is the common case, which is a URL fetched on first sight. The tail shows redirect chains
     * and retries, and a value at the budget is a URL the lane gave up on. Requirement 26.
     */
    private static readonly hopsUsed = new Histogram({
        name: 'ml_image_fetch_hops_used',
        help: 'Moves one URL made before the lane finished with it. A republish and a retry each count one. A redirect that stays on the same domain is bounded separately and counts none',
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
        help: 'Records this delay consumer finished with, by what happened: "released" back to the frontier, "failed" to publish, or "malformed" and dropped',
        labelNames: ['outcome'],
    })
    private static readonly waitSeconds = new Histogram({
        name: 'ml_image_fetch_retry_wait_seconds',
        help: 'Time a record still had to wait when this consumer read it. Compare with the period of the topic: a much shorter wait means the records arrived late, and the consumer is behind',
        buckets: [1, 10, 60, 300, 600, 1800, 3600],
    })

    public static incReleased(outcome: 'released' | 'failed' | 'malformed' | 'abandoned'): void {
        this.released.labels(outcome).inc()
    }
    public static observeWait(waitSeconds: number): void {
        this.waitSeconds.observe(waitSeconds)
    }
}

/**
 * How the lane's work divides between teams, without an unbounded label.
 *
 * The team ID space is in the low millions, so this bounds `pseudo_team` here rather than at the
 * database. The busiest teams keep their name, everything else is one `other` row, and the count of
 * distinct teams is an estimate in a single series. Requirements 29, 30, and 31.
 *
 * Nothing on this path holds the team ID, so a team ID label here would need the mirror to send it.
 */
export class ImageFetchTeamMetrics {
    private static source: TeamVolume | undefined

    private static readonly urlsByTeam = new Gauge({
        name: 'ml_image_fetch_team_urls',
        help: 'URLs handled for each of the busiest teams, with the rest summed as "other". The label is the team pseudonym the topic carries, not the team ID',
        labelNames: ['pseudo_team'],
        collect() {
            // Rebuilt at scrape rather than kept in step with the counts, so a team that drops out
            // of the top list loses its series instead of holding its last value.
            this.reset()
            for (const { team, count } of ImageFetchTeamMetrics.source?.top() ?? []) {
                this.labels(team).set(count)
            }
        },
    })
    private static readonly distinctTeams = new Gauge({
        name: 'ml_image_fetch_distinct_teams',
        help: 'About how many distinct teams this pod has handled URLs for, estimated rather than counted, because an exact set of a million team pseudonyms costs hundreds of megabytes',
        collect() {
            this.set(ImageFetchTeamMetrics.source?.distinctTeams() ?? 0)
        },
    })

    /** The consumer owns the counts. These gauges read them at scrape time. */
    public static track(volume: TeamVolume): void {
        this.source = volume
    }
}
