import { ConsoleMode, findLeaksBySnapshotFilePaths } from '@memlab/api'
import { CDPSession, Page } from '@playwright/test'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'

export interface HeapSnapshot {
    filePath: string
    heapSizeBytes: number
    timestamp: number
}

export interface LeakResult {
    leakedObjectCount: number
    leakedObjects: LeakedObject[]
    heapSizeChange: number
    analysisTimeMs: number
}

export interface LeakedObject {
    type: string
    count: number
    retainedSize: number
}

export interface MemoryLeakReport {
    pagesTraversed: string[]
    snapshots: {
        baseline: HeapSnapshot
        target: HeapSnapshot
        final: HeapSnapshot
    }
    leakResults: LeakResult
    timestamp: string
}

export async function takeHeapSnapshot(page: Page, snapshotDir: string, name: string): Promise<HeapSnapshot> {
    let client: CDPSession | null = null
    const filePath = path.join(snapshotDir, `${name}.heapsnapshot`)
    
    try {
        client = await page.context().newCDPSession(page)
        const chunks: string[] = []
        client.on('HeapProfiler.addHeapSnapshotChunk', (params: { chunk: string }) => {
            chunks.push(params.chunk)
        })

        await client.send('HeapProfiler.takeHeapSnapshot', { reportProgress: false })
        
        const snapshotData = chunks.join('')
        fs.writeFileSync(filePath, snapshotData)

        const heapSizeBytes = JSON.parse(snapshotData).snapshot?.meta?.total_size || snapshotData.length

        return {
            filePath,
            heapSizeBytes,
            timestamp: Date.now(),
        }
    } finally {
        if (client) {
            await client.detach()
        }
    }
}

export async function waitForPageStable(page: Page, timeoutMs: number = 5000): Promise<void> {
    await page.waitForLoadState('domcontentloaded')
    try {
        await page.waitForLoadState('networkidle', { timeout: timeoutMs })
    } catch {
        // networkidle may not occur with long-polling connections
    }
    await page.waitForTimeout(1000)
}

export async function forceGarbageCollection(page: Page): Promise<void> {
    let client: CDPSession | null = null
    try {
        client = await page.context().newCDPSession(page)
        await client.send('HeapProfiler.collectGarbage')
    } finally {
        if (client) {
            await client.detach()
        }
    }
}

export async function analyzeSnapshots(
    baselineSnapshot: HeapSnapshot,
    targetSnapshot: HeapSnapshot,
    finalSnapshot: HeapSnapshot
): Promise<LeakResult> {
    const startTime = Date.now()

    try {
        const leaks = await findLeaksBySnapshotFilePaths(
            baselineSnapshot.filePath,
            targetSnapshot.filePath,
            finalSnapshot.filePath,
            {
                workDir: path.dirname(baselineSnapshot.filePath),
                consoleMode: ConsoleMode.SILENT,
            }
        )

        const leakedObjects = aggregateLeakedObjects(leaks || [])

        return {
            leakedObjectCount: leaks?.length || 0,
            leakedObjects,
            heapSizeChange: finalSnapshot.heapSizeBytes - baselineSnapshot.heapSizeBytes,
            analysisTimeMs: Date.now() - startTime,
        }
    } catch (error) {
        console.error('Error analyzing snapshots:', error)
        return {
            leakedObjectCount: 0,
            leakedObjects: [],
            heapSizeChange: finalSnapshot.heapSizeBytes - baselineSnapshot.heapSizeBytes,
            analysisTimeMs: Date.now() - startTime,
        }
    }
}

function aggregateLeakedObjects(leaks: Array<{ name?: string; retainedSize?: number }>): LeakedObject[] {
    const objectMap = new Map<string, { count: number; retainedSize: number }>()

    for (const leak of leaks) {
        const type = leak.name || 'Unknown'
        const existing = objectMap.get(type) || { count: 0, retainedSize: 0 }
        objectMap.set(type, {
            count: existing.count + 1,
            retainedSize: existing.retainedSize + (leak.retainedSize || 0),
        })
    }

    return Array.from(objectMap.entries())
        .map(([type, data]) => ({
            type,
            count: data.count,
            retainedSize: data.retainedSize,
        }))
        .sort((a, b) => b.retainedSize - a.retainedSize)
        .slice(0, 10)
}

export function formatBytes(bytes: number): string {
    if (bytes === 0) {
        return '0 B'
    }

    const units = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024))
    const value = bytes / Math.pow(1024, i)

    return `${value >= 0 ? '+' : ''}${value.toFixed(2)} ${units[i]}`
}

export function generateReport(report: MemoryLeakReport): string {
    const { pagesTraversed, leakResults } = report

    let output = '## Memory Leak Detection Results\n\n'

    if (leakResults.leakedObjectCount > 0) {
        output += `**${leakResults.leakedObjectCount} potential memory leaks detected**\n\n`
    } else {
        output += '**No memory leaks detected**\n\n'
    }

    output += '### Summary\n'
    output += `- **Pages traversed:** ${pagesTraversed.length}\n`
    output += `- **Heap size change:** ${formatBytes(leakResults.heapSizeChange)}\n`
    output += `- **Analysis time:** ${leakResults.analysisTimeMs}ms\n\n`

    if (leakResults.leakedObjects.length > 0) {
        output += '### Top Leaked Objects\n'
        output += '| Type | Count | Retained Size |\n'
        output += '|------|-------|---------------|\n'
        for (const obj of leakResults.leakedObjects) {
            output += `| ${obj.type} | ${obj.count} | ${formatBytes(obj.retainedSize)} |\n`
        }
        output += '\n'
    }

    output += '---\n'
    output += '*Memory leak detection is informational and does not block PR merging.*\n'

    return output
}

export function createSnapshotDirectory(): string {
    const baseDir = process.env.CI
        ? path.join(process.cwd(), 'memory-leak-results')
        : path.join(os.tmpdir(), 'posthog-memory-leak-test')

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const dir = path.join(baseDir, timestamp)

    fs.mkdirSync(dir, { recursive: true })
    return dir
}

export function saveReport(report: MemoryLeakReport, snapshotDir: string): string {
    const reportPath = path.join(snapshotDir, 'memory-leak-report.json')
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))

    const markdownPath = path.join(snapshotDir, 'memory-leak-report.md')
    fs.writeFileSync(markdownPath, generateReport(report))

    return markdownPath
}
