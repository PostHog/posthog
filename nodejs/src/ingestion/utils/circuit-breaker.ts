import { Counter, Gauge } from 'prom-client'

import { logger } from '~/utils/logger'

const circuitBreakerState = new Gauge({
    name: 'ingestion_circuit_breaker_state',
    help: 'Circuit breaker state: 0 = closed, 1 = open',
    labelNames: ['name'],
})

const circuitBreakerProbeCounter = new Counter({
    name: 'ingestion_circuit_breaker_probes_total',
    help: 'Number of circuit breaker probes attempted',
    labelNames: ['name', 'result'],
})

export interface CircuitBreakerConfig {
    /** Identifier for metrics and logging. */
    name: string
    /** Consecutive failures before the circuit opens. Should match the
     *  retry wrapper's maxAttempts so the circuit trips as retries exhaust. */
    failureThreshold: number
    /** Initial backoff in ms between probes when the circuit is open. */
    initialBackoffMs: number
    /** Maximum backoff in ms between probes. */
    maxBackoffMs: number
    /** Number of items to include in each probe attempt. */
    probeSize: number
}

/**
 * Circuit breaker for external service dependencies.
 *
 * Tracks consecutive failures. When the failure threshold is reached,
 * the circuit opens. While open, callers should use waitForRecovery()
 * to block until a probe succeeds.
 *
 * Designed to work with a retry wrapper: the wrapper retries N times,
 * each retry increments the failure count, and the circuit trips on
 * the Nth failure. The next call sees the circuit open and blocks
 * instead of making another doomed request.
 */
export class CircuitBreaker {
    private open: boolean = false
    private consecutiveFailures: number = 0
    private config: CircuitBreakerConfig

    constructor(config: CircuitBreakerConfig) {
        this.config = config
    }

    /**
     * Record a failure. Opens the circuit when the threshold is reached.
     */
    recordFailure(): void {
        this.consecutiveFailures++

        if (this.consecutiveFailures >= this.config.failureThreshold && !this.open) {
            this.open = true
            circuitBreakerState.labels(this.config.name).set(1)
            logger.warn('⚠️', 'circuit_breaker_opened', {
                name: this.config.name,
                consecutiveFailures: this.consecutiveFailures,
            })
        }
    }

    /**
     * Record a success. Resets the failure count and closes the circuit.
     */
    recordSuccess(): void {
        this.consecutiveFailures = 0
        if (this.open) {
            this.open = false
            circuitBreakerState.labels(this.config.name).set(0)
            logger.info('✅', 'circuit_breaker_closed', { name: this.config.name })
        }
    }

    isOpen(): boolean {
        return this.open
    }

    getState(): string {
        return this.open ? 'open' : 'closed'
    }

    /**
     * Block until the probe function returns true, indicating the service
     * has recovered. Uses exponential backoff between probe attempts.
     * Closes the circuit when the probe succeeds.
     */
    async waitForRecovery(probe: (probeSize: number) => Promise<boolean>): Promise<void> {
        let backoffMs = this.config.initialBackoffMs

        while (this.open) {
            await new Promise((resolve) => setTimeout(resolve, backoffMs))

            logger.info('🔍', 'circuit_breaker_probing', {
                name: this.config.name,
                probeSize: this.config.probeSize,
                backoffMs,
            })

            const succeeded = await probe(this.config.probeSize)

            if (succeeded) {
                circuitBreakerProbeCounter.labels(this.config.name, 'success').inc()
                this.recordSuccess()
                return
            }

            circuitBreakerProbeCounter.labels(this.config.name, 'failed').inc()
            backoffMs = Math.min(backoffMs * 2, this.config.maxBackoffMs)
        }
    }
}
