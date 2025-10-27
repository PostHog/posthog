import { Gauge } from 'prom-client'

import { logger } from './logger'

// Current memory metrics
const processRssBytes = new Gauge({
    name: 'process_rss_bytes',
    help: 'Resident Set Size (RSS) in bytes - total memory allocated for the process',
})

const processHeapTotalBytes = new Gauge({
    name: 'process_heap_total_bytes',
    help: 'Total heap size in bytes',
})

const processHeapUsedBytes = new Gauge({
    name: 'process_heap_used_bytes',
    help: 'Heap memory currently used in bytes',
})

const processExternalBytes = new Gauge({
    name: 'process_external_bytes',
    help: 'Memory used by C++ objects bound to JavaScript objects managed by V8',
})

const processArrayBuffersBytes = new Gauge({
    name: 'process_array_buffers_bytes',
    help: 'Memory allocated for ArrayBuffers and SharedArrayBuffers',
})

// Growth rate metrics
const rssGrowthRateBytesPerSecond = new Gauge({
    name: 'process_rss_growth_rate_bytes_per_second',
    help: 'Rate of RSS growth in bytes per second (5 minute rolling average)',
})

const rssGrowthRateBytesPerHour = new Gauge({
    name: 'process_rss_growth_rate_bytes_per_hour',
    help: 'Rate of RSS growth in bytes per hour (extrapolated from 5 minute average)',
})

// Off-heap memory estimate
const offHeapMemoryBytes = new Gauge({
    name: 'process_off_heap_memory_bytes',
    help: 'Estimated off-heap memory (RSS - heap used - external)',
})

export class MemoryMonitor {
    private interval?: NodeJS.Timeout
    private initialRss: number = 0
    private initialTimestamp: number = 0
    private lastRss: number = 0
    private lastTimestamp: number = 0
    private rollingRssReadings: Array<{ rss: number; timestamp: number }> = []
    private readonly rollingWindowMs = 5 * 60 * 1000 // 5 minutes

    constructor(private readonly updateIntervalMs: number = 10000) {}

    start(): void {
        if (this.interval) {
            return
        }

        // Take initial reading
        const initialMemory = process.memoryUsage()
        this.initialRss = initialMemory.rss
        this.lastRss = initialMemory.rss
        this.initialTimestamp = Date.now()
        this.lastTimestamp = this.initialTimestamp

        logger.info('📊', 'Memory monitor started', {
            initialRss: this.formatBytes(this.initialRss),
            updateIntervalMs: this.updateIntervalMs,
        })

        // Update metrics immediately
        this.updateMetrics()

        // Set up recurring updates
        this.interval = setInterval(() => {
            this.updateMetrics()
        }, this.updateIntervalMs)

        // Don't prevent process exit
        this.interval.unref()
    }

    stop(): void {
        if (this.interval) {
            clearInterval(this.interval)
            this.interval = undefined
        }
    }

    private updateMetrics(): void {
        const memory = process.memoryUsage()
        const now = Date.now()

        // Update current memory metrics
        processRssBytes.set(memory.rss)
        processHeapTotalBytes.set(memory.heapTotal)
        processHeapUsedBytes.set(memory.heapUsed)
        processExternalBytes.set(memory.external)
        processArrayBuffersBytes.set(memory.arrayBuffers)

        // Calculate off-heap memory (approximate)
        const offHeap = memory.rss - memory.heapUsed - memory.external
        offHeapMemoryBytes.set(offHeap)

        // Add current reading to rolling window
        this.rollingRssReadings.push({ rss: memory.rss, timestamp: now })

        // Remove readings older than the rolling window
        const cutoffTime = now - this.rollingWindowMs
        this.rollingRssReadings = this.rollingRssReadings.filter((reading) => reading.timestamp > cutoffTime)

        // Calculate growth rate using rolling window
        if (this.rollingRssReadings.length >= 2) {
            const oldestReading = this.rollingRssReadings[0]
            const newestReading = this.rollingRssReadings[this.rollingRssReadings.length - 1]

            const rssDiff = newestReading.rss - oldestReading.rss
            const timeDiffSeconds = (newestReading.timestamp - oldestReading.timestamp) / 1000

            if (timeDiffSeconds > 0) {
                const growthRatePerSecond = rssDiff / timeDiffSeconds
                const growthRatePerHour = growthRatePerSecond * 3600

                rssGrowthRateBytesPerSecond.set(growthRatePerSecond)
                rssGrowthRateBytesPerHour.set(growthRatePerHour)
            }
        }

        // Log summary periodically (every 5 minutes)
        const timeSinceStart = now - this.initialTimestamp
        if (timeSinceStart > 0 && timeSinceStart % (5 * 60 * 1000) < this.updateIntervalMs) {
            this.logMemorySummary(memory, now)
        }

        this.lastRss = memory.rss
        this.lastTimestamp = now
    }

    private logMemorySummary(memory: NodeJS.MemoryUsage, now: number): void {
        const totalGrowth = memory.rss - this.initialRss
        const timeSinceStartSeconds = (now - this.initialTimestamp) / 1000
        const averageGrowthPerSecond = totalGrowth / timeSinceStartSeconds
        const averageGrowthPerHour = averageGrowthPerSecond * 3600

        const offHeap = memory.rss - memory.heapUsed - memory.external

        logger.info('📊', 'Memory usage summary', {
            uptime_minutes: Math.round(timeSinceStartSeconds / 60),
            current: {
                rss: this.formatBytes(memory.rss),
                heap_used: this.formatBytes(memory.heapUsed),
                heap_total: this.formatBytes(memory.heapTotal),
                external: this.formatBytes(memory.external),
                array_buffers: this.formatBytes(memory.arrayBuffers),
                off_heap_estimate: this.formatBytes(offHeap),
            },
            growth: {
                total_rss_growth: this.formatBytes(totalGrowth),
                average_per_hour: this.formatBytes(averageGrowthPerHour),
                percentage: `${((totalGrowth / this.initialRss) * 100).toFixed(2)}%`,
            },
            ratios: {
                heap_to_rss: `${((memory.heapUsed / memory.rss) * 100).toFixed(1)}%`,
                off_heap_to_rss: `${((offHeap / memory.rss) * 100).toFixed(1)}%`,
            },
        })
    }

    private formatBytes(bytes: number): string {
        if (bytes < 1024) {
            return `${bytes} B`
        }
        if (bytes < 1024 * 1024) {
            return `${(bytes / 1024).toFixed(2)} KB`
        }
        if (bytes < 1024 * 1024 * 1024) {
            return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
        }
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
    }

    // Public method to get current memory stats for debugging
    public getCurrentStats() {
        const memory = process.memoryUsage()
        const now = Date.now()
        const totalGrowth = memory.rss - this.initialRss
        const timeSinceStartSeconds = (now - this.initialTimestamp) / 1000

        return {
            rss: memory.rss,
            heapUsed: memory.heapUsed,
            heapTotal: memory.heapTotal,
            external: memory.external,
            arrayBuffers: memory.arrayBuffers,
            offHeap: memory.rss - memory.heapUsed - memory.external,
            totalGrowth,
            uptimeSeconds: timeSinceStartSeconds,
            growthPerHour: timeSinceStartSeconds > 0 ? (totalGrowth / timeSinceStartSeconds) * 3600 : 0,
        }
    }
}
