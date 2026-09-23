import { Counter, Gauge, Histogram } from 'prom-client'

import { ConcurrencyController } from '~/common/utils/concurrencyController'

import type { ConfigurationFetchResult } from './configuration-policy'
import type { ConfigurationFile } from './crawl-history'

export type ProcessingStage =
    | 'batch_parse'
    | 'batch_filter'
    | 'batch_history_read'
    | 'batch_fetch'
    | 'batch_prepare_republish'
    | 'batch_history_write'
    | 'batch_republish_flush'
    | 'batch_finalize'
    | 'batch_dead_letter'
    | 'consumer_join'
    | 'consumer_process'
    | 'candidate_admission'
    | 'candidate_work'
    | 'candidate_policy'
    | 'candidate_fetch'
    | 'image_publish_admission'
    | 'image_publish_delivery'
    | 'configuration_fetch'
    | `configuration_${'request_capacity' | 'origin_crawl_delay' | 'registrable_domain_rate' | 'http'}`
    | `image_${'request_capacity' | 'origin_crawl_delay' | 'registrable_domain_rate' | 'http'}`

export type ConfigurationFetchReason =
    | ConfigurationFetchResult['outcome']
    | 'invalid_url'
    | 'request_error'
    | 'timeout'
    | 'redirect_limit'
    | 'cross_domain_redirect'
    | 'invalid_redirect'
    | 'missing_location'
    | 'http_429'
    | 'http_5xx'
    | 'unexpected_status'
    | 'body_limit'
    | 'invalid_utf8'
    | 'invalid_document'

export class ImageFetchProcessingMetrics {
    private static readonly active = new Map<ProcessingStage, Map<symbol, number>>()
    private static readonly queues = new Set<{ readonly candidateCount: number }>()

    private static readonly activeGauge = new Gauge({
        name: 'ml_image_fetch_stage_active',
        help: 'Active operations by stage; nested stages overlap and must not be summed together',
        labelNames: ['stage'],
        collect() {
            for (const [stage, operations] of ImageFetchProcessingMetrics.active) {
                this.set({ stage }, operations.size)
            }
        },
    })

    private static readonly oldestGauge = new Gauge({
        name: 'ml_image_fetch_stage_oldest_seconds',
        help: 'Age of the oldest active operation in each stage, or zero when idle',
        labelNames: ['stage'],
        collect() {
            const now = performance.now()
            for (const [stage, operations] of ImageFetchProcessingMetrics.active) {
                const first = operations.values().next().value
                this.set({ stage }, first === undefined ? 0 : Math.max(0, now - first) / 1000)
            }
        },
    })

    private static readonly queuedCandidates = new Gauge({
        name: 'ml_image_fetch_candidates_queued',
        help: 'Candidates waiting for selection from all active passes, before candidate admission',
        collect() {
            let count = 0
            for (const queue of ImageFetchProcessingMetrics.queues) {
                count += queue.candidateCount
            }
            this.set(count)
        },
    })

    private static readonly duration = new Histogram({
        name: 'ml_image_fetch_stage_duration_seconds',
        help: 'Elapsed time of finished stage visits, including failed operations; nested stages overlap',
        labelNames: ['stage'],
        buckets: [0.001, 0.01, 0.1, 0.5, 1, 5, 10, 30, 60, 120, 240, 600],
    })

    public static readonly joinedBatches = new Histogram({
        name: 'ml_image_fetch_joined_batches',
        help: 'Consumer batches in each dispatched fetch group',
        buckets: [1, 2, 4, 8, 12, 16],
    })

    private static readonly configurationLookups = new Counter({
        name: 'ml_image_fetch_configuration_lookups_total',
        help: 'Configuration lookups by source and observed status; shared requests count once per caller',
        labelNames: ['file', 'source', 'outcome'],
    })

    private static readonly configurationFetches = new Counter({
        name: 'ml_image_fetch_configuration_fetches_total',
        help: 'Completed configuration fetches, once per redirect chain, by final outcome and reason',
        labelNames: ['file', 'outcome', 'reason'],
    })

    public static start(stage: ProcessingStage): ProcessingStageTimer {
        return new ProcessingStageTimer(stage)
    }

    public static enter(stage: ProcessingStage): symbol {
        let operations = this.active.get(stage)
        if (!operations) {
            operations = new Map()
            this.active.set(stage, operations)
        }
        const id = Symbol()
        operations.set(id, performance.now())
        return id
    }

    public static leave(stage: ProcessingStage, id: symbol): void {
        const operations = this.active.get(stage)
        const started = operations?.get(id)
        if (started !== undefined) {
            operations!.delete(id)
            this.duration.observe({ stage }, Math.max(0, performance.now() - started) / 1000)
        }
    }

    public static async measure<T>(stage: ProcessingStage, operation: () => Promise<T>): Promise<T> {
        const timer = this.start(stage)
        try {
            return await operation()
        } finally {
            timer.finish()
        }
    }

    public static async runLimited<T>(
        controller: ConcurrencyController,
        waitingStage: ProcessingStage,
        runningStage: ProcessingStage,
        options: { debugTag: string; fn: () => Promise<T> }
    ): Promise<T> {
        const timer = this.start(waitingStage)
        try {
            return await controller.run({
                ...options,
                fn: () => {
                    timer.move(runningStage)
                    return options.fn()
                },
            })
        } finally {
            timer.finish()
        }
    }

    public static trackQueue(queue: { readonly candidateCount: number }): () => void {
        this.queues.add(queue)
        return () => {
            this.queues.delete(queue)
        }
    }

    public static observeConfigurationLookup(
        file: ConfigurationFile,
        source: 'cache' | 'shared' | 'network',
        outcome: ConfigurationFetchResult['outcome'] | 'error'
    ): void {
        this.configurationLookups.inc({ file, source, outcome })
    }

    public static observeConfigurationFetch(
        file: ConfigurationFile,
        result: ConfigurationFetchResult,
        reason: ConfigurationFetchReason
    ): ConfigurationFetchResult {
        this.configurationFetches.inc({ file, outcome: result.outcome, reason })
        return result
    }
}

export class ProcessingStageTimer {
    private id: symbol | undefined

    constructor(private stage: ProcessingStage) {
        this.id = ImageFetchProcessingMetrics.enter(stage)
    }

    public move(stage: ProcessingStage): void {
        this.finish()
        this.stage = stage
        this.id = ImageFetchProcessingMetrics.enter(stage)
    }

    public finish(): void {
        if (this.id !== undefined) {
            ImageFetchProcessingMetrics.leave(this.stage, this.id)
            this.id = undefined
        }
    }
}
