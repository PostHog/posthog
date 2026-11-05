import clsx from 'clsx'
import { Suspense } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { LemonMarkdownProps } from './LemonMarkdown'

const LemonMarkdownChunk = lazyWithRetry(() => import('./LemonMarkdown').then((m) => ({ default: m.LemonMarkdown })))

/**
 * `LemonMarkdown` loaded on first render. Use it in code that ships on every page.
 * While the chunk loads, the raw text holds roughly the rendered height invisibly, so content below does not jump.
 */
export function LazyLemonMarkdown(props: LemonMarkdownProps): JSX.Element {
    return (
        <Suspense
            fallback={
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
