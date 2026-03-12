import { EventLoopUtilization, performance } from 'perf_hooks'
import { Gauge } from 'prom-client'

const eventLoopUtilizationGauge = new Gauge({
    name: 'event_loop_utilization',
    help: 'Proportion of time the event loop is busy',
})

export class NodeInstrumentation {
    private threadPerformanceInterval?: NodeJS.Timeout
    private lastEventLoopUtilization?: EventLoopUtilization

    constructor(private instrumentThreadPerformance: boolean) {}

    setupThreadPerformanceInterval(): void {
        if (!this.instrumentThreadPerformance) {
            return
        }

        if (this.threadPerformanceInterval) {
            clearInterval(this.threadPerformanceInterval)
        }

        // Initialize the last utilization on first call
        if (!this.lastEventLoopUtilization) {
            this.lastEventLoopUtilization = performance.eventLoopUtilization()
        }

        this.threadPerformanceInterval = setInterval(() => {
            const current = performance.eventLoopUtilization()
            const delta = performance.eventLoopUtilization(this.lastEventLoopUtilization, current)
            this.lastEventLoopUtilization = current

            eventLoopUtilizationGauge.set(delta.utilization)
        }, 1000)
    }

    cleanup(): void {
        if (this.threadPerformanceInterval) {
            clearInterval(this.threadPerformanceInterval)
        }
    }
}
