import { Counter, Gauge, Histogram } from 'prom-client'

export type UrlDropReason =
    | 'malformed'
    | 'unsupported_version'
    | 'stale'
    | 'bad_ref'
    | 'bad_url'
    | 'foreign_domain'
    | 'oversized_record'

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
        help: 'URLs refused before dedup, by reason: "stale" (older than the age limit), "malformed" / "unsupported_version" / "oversized_record" (the record did not parse), "bad_ref" / "bad_url" (an entry inside a record did not parse), "foreign_domain" (the host sits outside the domain the record is keyed by)',
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
        help: 'URLs carried by one Kafka record. The producer caps this, so a distribution pinned at the cap means records are being split and the cap is the binding constraint',
        buckets: [1, 2, 4, 8, 16, 32, 64],
    })
    private static readonly storeErrors = new Counter({
        name: 'ml_image_fetch_consumer_store_errors_total',
        help: 'Sighting-store keys that failed, by operation. A failed read makes the lane treat a known URL as new, so the measured hit rate understates the real one. A failed write leaves the URL unrecorded, so the next pod to see it counts it again',
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
