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

interface HeapSnapshotData {
    snapshot: {
        meta: {
            node_fields: string[]
            node_types: (string | string[])[]
            edge_fields: string[]
            edge_types: (string | string[])[]
        }
    }
    nodes: number[]
    edges: number[]
    strings: string[]
}

interface DOMNodeInfo {
    nodeId: number
    type: string
    name: string
    className?: string
    id?: string
    dataAttr?: string
    tagName?: string
}

export interface LeakResult {
    leakedObjectCount: number
    leakedObjects: LeakedObject[]
    heapSizeChange: number
    analysisTimeMs: number
    rawLeaks?: unknown[]
}

export interface LeakedObject {
    type: string
    count: number
    retainedSize: number
    retainerPath?: string
    domIdentifiers?: string[]
    likelyLibrary?: string
}

export interface MemoryLeakReport {
    testName: string
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

function parseHeapSnapshotForDOMNodes(snapshotPath: string): Map<number, DOMNodeInfo> {
    const domNodes = new Map<number, DOMNodeInfo>()

    try {
        const data: HeapSnapshotData = JSON.parse(fs.readFileSync(snapshotPath, 'utf-8'))
        const { nodes, edges, strings, snapshot } = data
        const { node_fields, edge_fields } = snapshot.meta

        const nodeFieldCount = node_fields.length
        const edgeFieldCount = edge_fields.length

        const nameIdx = node_fields.indexOf('name')
        const idIdx = node_fields.indexOf('id')
        const edgeCountIdx = node_fields.indexOf('edge_count')
        const detachednessIdx = node_fields.indexOf('detachedness')

        const edgeNameIdx = edge_fields.indexOf('name_or_index')
        const edgeToNodeIdx = edge_fields.indexOf('to_node')

        const nodeEdgeOffsets = new Map<number, number>()
        let edgeOffset = 0
        for (let nodeIdx = 0; nodeIdx < nodes.length; nodeIdx += nodeFieldCount) {
            nodeEdgeOffsets.set(nodeIdx, edgeOffset)
            edgeOffset += nodes[nodeIdx + edgeCountIdx] * edgeFieldCount
        }

        function getNodeEdges(nodeOffset: number): Array<{ edgeName: string; toNodeOffset: number }> {
            const edgeCount = nodes[nodeOffset + edgeCountIdx]
            const startEdge = nodeEdgeOffsets.get(nodeOffset) || 0
            const result: Array<{ edgeName: string; toNodeOffset: number }> = []

            for (let e = 0; e < edgeCount; e++) {
                const edgeBase = startEdge + e * edgeFieldCount
                const edgeNameOrIdx = edges[edgeBase + edgeNameIdx]
                const edgeName =
                    typeof edgeNameOrIdx === 'number' ? strings[edgeNameOrIdx] || '' : String(edgeNameOrIdx)
                const toNodeOffset = edges[edgeBase + edgeToNodeIdx]
                result.push({ edgeName, toNodeOffset })
            }
            return result
        }

        for (let nodeIdx = 0; nodeIdx < nodes.length; nodeIdx += nodeFieldCount) {
            const detachedness = detachednessIdx >= 0 ? nodes[nodeIdx + detachednessIdx] : 0
            const nodeName = strings[nodes[nodeIdx + nameIdx]] || ''
            const nodeId = nodes[nodeIdx + idIdx]

            const isDetachedDOM =
                detachedness > 0 &&
                (nodeName.includes('HTML') || nodeName.includes('SVG')) &&
                nodeName.includes('Element')

            if (isDetachedDOM) {
                const info: DOMNodeInfo = {
                    nodeId,
                    type: nodeName,
                    name: nodeName,
                }

                const nodeEdges = getNodeEdges(nodeIdx)

                const reactPropsEdge = nodeEdges.find((e) => e.edgeName.startsWith('__reactProps'))
                if (reactPropsEdge) {
                    const propsEdges = getNodeEdges(reactPropsEdge.toNodeOffset)

                    for (const propEdge of propsEdges) {
                        const propValue = strings[nodes[propEdge.toNodeOffset + nameIdx]] || ''

                        if (propEdge.edgeName === 'className' && propValue) {
                            info.className = propValue
                        } else if (propEdge.edgeName === 'id' && propValue && !propValue.startsWith(':r')) {
                            info.id = propValue
                        } else if (propEdge.edgeName === 'data-attr' && propValue) {
                            info.dataAttr = `[data-attr="${propValue}"]`
                        } else if (propEdge.edgeName === 'data-testid' && propValue) {
                            info.dataAttr = `[data-testid="${propValue}"]`
                        }
                    }
                }

                if (info.className || info.id || info.dataAttr) {
                    domNodes.set(nodeId, info)
                }
            }
        }
    } catch (error) {
        console.error('[memory-leak] Error parsing heap snapshot:', error)
    }

    return domNodes
}

const TAILWIND_PATTERNS =
    /^(flex|grid|block|inline|hidden|absolute|relative|fixed|sticky|top-|bottom-|left-|right-|z-|w-|h-|min-|max-|m-|mx-|my-|mt-|mb-|ml-|mr-|p-|px-|py-|pt-|pb-|pl-|pr-|gap-|space-|text-|font-|leading-|tracking-|bg-|border|rounded|shadow|opacity-|transition|duration-|ease-|delay-|animate-|transform|scale-|rotate-|translate-|skew-|origin-|overflow-|cursor-|pointer-|select-|resize|appearance-|outline-|ring-|fill-|stroke-|items-|justify-|self-|place-|content-|order-|grow|shrink|basis-|table|float-|clear-|object-|aspect-|columns-|break-|box-|isolat|mix-|filter|backdrop-|sr-only|not-sr-only|forced-|accent-|caret-|scroll-|snap-|touch-|will-|divide-|truncate|antialiased|subpixel-|hyphens-|whitespace-|indent-|align-|underline|overline|line-through|no-underline|decoration-|list-|col-|row-|auto-|fr|size-|sparkle)/

function isUnusableClassName(c: string): boolean {
    if (c.includes('[') || c.includes('var(--') || c.includes(':')) {
        return true
    }
    if (c.startsWith('-') && c.length > 1) {
        return true
    }
    if (c.includes('(') || c.includes(')') || c.includes(' ') || c.includes('/')) {
        return true
    }
    if (c.startsWith('Toastify') || c.startsWith('react-') || c.startsWith('Spinner')) {
        return true
    }
    if (c.length <= 3 || /^-?\d/.test(c)) {
        return true
    }
    return TAILWIND_PATTERNS.test(c)
}

function isPostHogClassName(c: string): boolean {
    if (c.includes('__') || (c.includes('--') && !c.includes('var('))) {
        return true
    }
    if (/^[A-Z]/.test(c) || c.startsWith('scene-')) {
        return true
    }
    return false
}

function extractDOMSelectorsFromSnapshot(snapshotPath: string): string[] {
    const domNodes = parseHeapSnapshotForDOMNodes(snapshotPath)
    const selectors: string[] = []

    for (const node of domNodes.values()) {
        if (node.dataAttr && !node.dataAttr.includes('/') && !node.dataAttr.includes(' ')) {
            selectors.push(node.dataAttr)
            continue
        }

        if (node.id && !node.id.includes('(') && !node.id.includes(' ')) {
            selectors.push(`#${node.id}`)
            continue
        }

        if (node.className) {
            const classes = node.className.split(/\s+/).filter((c) => c && !c.startsWith('css-'))
            const usableClasses = classes.filter((c) => !isUnusableClassName(c))
            const posthogClass = usableClasses.find(isPostHogClassName)
            if (posthogClass) {
                selectors.push(`.${posthogClass}`)
                continue
            }
            if (usableClasses.length > 0) {
                selectors.push(`.${usableClasses[0]}`)
            }
        }
    }

    return [...new Set(selectors)].slice(0, 10)
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

        if (leaks && leaks.length > 0) {
            // eslint-disable-next-line no-console
            console.log('[memory-leak] Sample leak structure:', JSON.stringify(leaks[0], null, 2))
        }

        const domSelectors = extractDOMSelectorsFromSnapshot(finalSnapshot.filePath)
        // eslint-disable-next-line no-console
        console.log('[memory-leak] Extracted DOM selectors from snapshot:', domSelectors)

        const leakedObjects = aggregateLeakedObjects(leaks || [], domSelectors)

        return {
            leakedObjectCount: leaks?.length || 0,
            leakedObjects,
            heapSizeChange: finalSnapshot.heapSizeBytes - baselineSnapshot.heapSizeBytes,
            analysisTimeMs: Date.now() - startTime,
            rawLeaks: leaks || [],
        }
    } catch (error) {
        console.error('Error analyzing snapshots:', error)
        return {
            leakedObjectCount: 0,
            leakedObjects: [],
            heapSizeChange: finalSnapshot.heapSizeBytes - baselineSnapshot.heapSizeBytes,
            analysisTimeMs: Date.now() - startTime,
            rawLeaks: [],
        }
    }
}

interface LeakTrace {
    type: string
    retainedSize: number
    retainerPath: string
    domIdentifiers: string[]
    likelyLibrary?: string
}

const LIBRARY_SIGNATURES: Array<{ pattern: RegExp; library: string }> = [
    { pattern: /posthog|JS_POSTHOG_HOST/i, library: 'posthog-js' },
    { pattern: /sentry|SentryIntegration/i, library: 'Sentry' },
    { pattern: /kea|_isKeaBuild|builtLogics/i, library: 'kea' },
    { pattern: /_reactListening|__reactFiber|__reactProps/i, library: 'React' },
    { pattern: /rrweb|getRecordNetworkPlugin/i, library: 'rrweb' },
    { pattern: /redux|dispatch|reducer/i, library: 'Redux' },
]

function detectLibraryFromTrace(traceKeys: string[]): string | undefined {
    const traceText = traceKeys.join(' ')
    for (const { pattern, library } of LIBRARY_SIGNATURES) {
        if (pattern.test(traceText)) {
            return library
        }
    }
    return undefined
}

const DOM_ELEMENT_PATTERN = /^(HTML\w+Element|SVG\w+|EventListener|V8Event\w*)$/

function extractLeakInfo(leak: Record<string, unknown>): LeakTrace | null {
    const keys = Object.keys(leak)
    const domPathSteps: string[] = []
    let leakedType = 'Unknown'
    let retainedSize = 0

    for (const key of keys) {
        const stepMatch = key.match(/\[([^\]]+)\]\((\w+)\)/)
        if (stepMatch) {
            const [, nodeName] = stepMatch
            const cleanName = nodeName.replace(/^Detached\s+/, '')
            if (DOM_ELEMENT_PATTERN.test(cleanName)) {
                domPathSteps.push(cleanName)
            }
        }

        if (key.includes('$memLabTag:leaked')) {
            const typeMatch = key.match(/\[([^\]]+)\]\((\w+)\)/)
            leakedType = typeMatch ? `${typeMatch[1]} (${typeMatch[2]})` : 'Unknown'

            const sizeMatch = key.match(/\$retained-size:(\d+)/)
            retainedSize = sizeMatch ? parseInt(sizeMatch[1], 10) : 0
        }
    }

    if (leakedType === 'Unknown') {
        return null
    }

    return {
        type: leakedType,
        retainedSize,
        retainerPath: [...new Set(domPathSteps)].slice(-5).join(' → ') || 'unknown path',
        domIdentifiers: [],
        likelyLibrary: detectLibraryFromTrace(keys),
    }
}

function aggregateLeakedObjects(leaks: unknown[], snapshotDOMSelectors: string[] = []): LeakedObject[] {
    const objectMap = new Map<string, LeakedObject>()

    for (const leak of leaks) {
        if (typeof leak !== 'object' || leak === null) {
            continue
        }
        const info = extractLeakInfo(leak as Record<string, unknown>)
        if (!info) {
            continue
        }

        const existing = objectMap.get(info.type)
        if (existing) {
            existing.count += 1
            existing.retainedSize += info.retainedSize
        } else {
            objectMap.set(info.type, {
                type: info.type,
                count: 1,
                retainedSize: info.retainedSize,
                retainerPath: info.retainerPath,
                domIdentifiers: [],
                likelyLibrary: info.likelyLibrary,
            })
        }
    }

    const results = Array.from(objectMap.values())
        .sort((a, b) => b.retainedSize - a.retainedSize)
        .slice(0, 10)

    if (snapshotDOMSelectors.length > 0 && results.length > 0) {
        results[0].domIdentifiers = snapshotDOMSelectors.slice(0, 10)
    }

    return results
}

function formatBytes(bytes: number): string {
    const units = ['B', 'KB', 'MB', 'GB']
    const absBytes = Math.abs(bytes)

    if (absBytes < 1) {
        const value = bytes
        return `${value >= 0 ? '+' : ''}${Math.abs(value).toFixed(2)} ${units[0]}`
    }

    const rawIndex = Math.log(absBytes) / Math.log(1024)
    const i = Math.min(units.length - 1, Math.max(0, Math.floor(rawIndex)))
    const value = bytes / Math.pow(1024, i)

    return `${value >= 0 ? '+' : ''}${Math.abs(value).toFixed(2)} ${units[i]}`
}

export function generateReport(report: MemoryLeakReport): string {
    const { testName, pagesTraversed, leakResults } = report

    let output = `## Memory Leak Detection: ${testName}\n\n`

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
        output += '### Top Leaked Objects\n\n'
        for (const obj of leakResults.leakedObjects) {
            output += `#### ${obj.type}\n`
            output += `- **Count:** ${obj.count}\n`
            output += `- **Retained size:** ${formatBytes(obj.retainedSize)}\n`
            if (obj.likelyLibrary) {
                output += `- **📦 Likely from:** ${obj.likelyLibrary}\n`
            }
            if (obj.domIdentifiers && obj.domIdentifiers.length > 0) {
                output += `- **🎯 DOM selectors:** \`${obj.domIdentifiers.join('`, `')}\`\n`
            }
            if (obj.retainerPath && obj.retainerPath !== 'unknown path') {
                // Clean up retainer path - keep only DOM element types, not minified names
                const cleanPath = obj.retainerPath
                    .split(' → ')
                    .filter((p) => /^HTML\w+Element$|^SVG\w+$|^EventListener$|^V8Event/.test(p))
                    .join(' → ')
                if (cleanPath) {
                    output += `- **Leak path:** \`${cleanPath}\`\n`
                }
            }
            output += '\n'
        }
    }

    if (leakResults.leakedObjectCount > 0) {
        output += '### How to Investigate\n\n'
        output += '1. **Use DOM selectors** to find the component in your codebase:\n'
        output += '   - Search for `data-attr="..."` values in JSX/TSX files\n'
        output += '   - Search for class names like `LemonButton`, `InsightCard`, etc.\n'
        output += '2. **Leak path** shows which DOM element is leaking (e.g., `HTMLImageElement → EventListener`)\n'
        output += '3. **Common leak patterns:**\n'
        output += '   - `EventListener` → missing `removeEventListener` in useEffect cleanup\n'
        output += '   - `HTMLElement` → DOM node stored in ref/state not cleared on unmount\n'
        output += '   - Component subscriptions → missing cleanup in useEffect return\n'
        output += '4. Download `raw-leak-traces.json` for detailed heap analysis\n\n'
        output += '> **Note:** Minified names in traces (like `gft`, `Q0`) are from third-party libraries\n'
        output += '> (posthog-js, etc.) and cannot be resolved. Focus on DOM selectors instead.\n\n'
    }

    output += '---\n'
    output += '*Memory leak detection is informational and does not block PR merging.*\n'

    return output
}

export function createSnapshotDirectory(testName?: string): string {
    const baseDir = process.env.CI
        ? path.join(process.cwd(), 'memory-leak-results')
        : path.join(os.tmpdir(), 'posthog-memory-leak-test')

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const dirName = testName ? `${timestamp}-${testName}` : timestamp
    const dir = path.join(baseDir, dirName)

    fs.mkdirSync(dir, { recursive: true })
    return dir
}

export function saveReport(report: MemoryLeakReport, snapshotDir: string): string {
    const reportPath = path.join(snapshotDir, 'memory-leak-report.json')
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))

    const markdownPath = path.join(snapshotDir, 'memory-leak-report.md')
    fs.writeFileSync(markdownPath, generateReport(report))

    if (report.leakResults.rawLeaks && report.leakResults.rawLeaks.length > 0) {
        const rawLeaksPath = path.join(snapshotDir, 'raw-leak-traces.json')
        fs.writeFileSync(rawLeaksPath, JSON.stringify(report.leakResults.rawLeaks, null, 2))
    }

    return markdownPath
}
