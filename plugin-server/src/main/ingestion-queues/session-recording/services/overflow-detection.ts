import LRUCache from 'lru-cache'
import { Gauge } from 'prom-client'

import { Limiter } from '../../../../utils/token-bucket'

export enum OverflowState {
    Okay,
    Triggered, // Recently triggered the overflow detection
    Cooldown, // Already triggered the overflow detection earlier than cooldownSeconds
}

export const overflowTriggeredGauge = new Gauge({
    name: 'overflow_detection_triggered_total',
    help: 'Number of entities that triggered overflow detection.',
})

/**
 * OverflowDetection handles consumer-side detection of hot partitions by
 * accounting for data volumes per entity (a session_id, a distinct_id...).
 *
 * The first time that the observed spike crosses the thresholds set via burstCapacity
 * and replenishRate, observe returns Triggered. Subsequent calls will return Cooldown
 * until cooldownSeconds is reached.
 */
export class OverflowDetection {
    private limiter: Limiter
    private triggered: LRUCache<string, boolean>

    constructor(burstCapacity: number, replenishRate: number, cooldownSeconds: number) {
        this.limiter = new Limiter(burstCapacity, replenishRate)
        this.triggered = new LRUCache({ max: 1_000_000, maxAge: cooldownSeconds * 1000 })
    }

    public observe(key: string, quantity: number, now?: number): OverflowState {
        if (this.triggered.has(key)) {
            return OverflowState.Cooldown
        }
        if (this.limiter.consume(key, quantity, now)) {
            return OverflowState.Okay
        }
        this.triggered.set(key, true)
        overflowTriggeredGauge.inc(1)
        return OverflowState.Triggered
    }
}
