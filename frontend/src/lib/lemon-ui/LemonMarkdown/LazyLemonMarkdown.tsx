import clsx from 'clsx'
import { Suspense } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { LemonMarkdownProps } from './LemonMarkdown'

// react-markdown and its remark plugins are large, so surfaces that every page mounts load them on demand.
const LemonMarkdownChunk = lazyWithRetry(() => import('./LemonMarkdown').then((m) => ({ default: m.LemonMarkdown })))

/** `LemonMarkdown` loaded on first render. Use it in code that ships on every page. */
export function LazyLemonMarkdown(props: LemonMarkdownProps): JSX.Element {
    return (
        <Suspense
            fallback={
                // The raw text holds roughly the rendered height, so the formatted text does not push content down.
                <div
                    className={clsx('invisible whitespace-pre-line [overflow-wrap:anywhere]', props.className)}
                    aria-busy
                >
                    {props.children}
                </div>
            }
        >
            <LemonMarkdownChunk {...props} />
        </Suspense>
    )
}
