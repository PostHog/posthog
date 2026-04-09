declare module '@memlab/lens/dist/memlens.lib.bundle.js' {
    interface MemLensScanResult {
        totalElements: number
        totalDetachedElements: number
        detachedComponentToFiberNodeCount: Map<string, number>
        componentToFiberNodeCount: Map<string, number>
        start: number
        end: number
    }

    interface MemLensScanner {
        subscribe: (callback: (result: MemLensScanResult) => void) => () => void
        start: () => void
        stop: () => void
        dispose: () => void
    }

    interface MemLensScanOptions {
        scanIntervalMs?: number
        trackEventListenerLeaks?: boolean
    }

    export function createReactMemoryScan(options?: MemLensScanOptions): MemLensScanner
}
