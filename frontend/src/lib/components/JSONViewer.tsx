import './JSONViewer.scss'

import type { ReactJsonViewProps } from '@microlink/react-json-view'
import { useValues } from 'kea'
import { Suspense } from 'react'

import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const ReactJson = lazyWithRetry(() => import('@microlink/react-json-view'))

export enum JSONViewerTheme {
    DARK = 'railscasts',
    LIGHT = 'rjv-default',
}

export function JSONViewerInner({
    name = null, // Don't label the root node as "root" by default
    displayDataTypes = false, // Reduce visual clutter
    displayObjectSize = false, // Reduce visual clutter
    // Truncate very long strings by default — they stay one click away from full expansion. Without
    // this, pathologically long values (LLM prompts/completions, tool args, base64 image blobs in
    // AI traces) render inline in full, which thrashes layout and makes expand/collapse clicks lag.
    collapseStringsAfterLength = 10000,
    ...props
}: ReactJsonViewProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <ReactJson // eslint-disable-line react/forbid-elements
            // HACK: Weirdly when `theme` prop changes on the same component instance, the JSON viewer drops `style`
            // we provided, so we force a different identity between dark and light mode with `key`, to re-render fully
            key={isDarkModeOn ? 'dark' : 'light'}
            style={{ background: 'transparent', overflowWrap: 'anywhere' }} // More aggressive wrapping against overflow
            theme={isDarkModeOn ? 'railscasts' : 'rjv-default'}
            name={name}
            displayDataTypes={displayDataTypes}
            displayObjectSize={displayObjectSize}
            collapseStringsAfterLength={collapseStringsAfterLength}
            enableClipboard={(copy) => {
                // The library wraps string values in quotes.
                // Re-copy with raw string value so users get the actual content.
                const text = typeof copy.src === 'string' ? copy.src : JSON.stringify(copy.src, null, 2)
                navigator.clipboard.writeText(text).catch((e) => console.warn('Failed to copy to clipboard', e))
            }}
            {...props}
        />
    )
}

export function JSONViewerSkeleton(): JSX.Element {
    return (
        <WrappingLoadingSkeleton fullWidth>
            <span className="block font-mono text-xs leading-5">
                <span className="block">{'{'}</span>
                <span className="block pl-4">"loading": "json content",</span>
                <span className="block pl-4">"please": "wait"</span>
                <span className="block">{'}'}</span>
            </span>
        </WrappingLoadingSkeleton>
    )
}

export function JSONViewer(props: ReactJsonViewProps): JSX.Element {
    return (
        <Suspense fallback={<JSONViewerSkeleton />}>
            <JSONViewerInner {...props} />
        </Suspense>
    )
}
