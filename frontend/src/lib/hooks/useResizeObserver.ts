import ResizeObserver from 'resize-observer-polyfill'
import useResizeObserverImport from 'use-resize-observer'

// Use polyfill only if needed
if (!window.ResizeObserver) {
    window.ResizeObserver = ResizeObserver
}

export const useResizeObserver = useResizeObserverImport
