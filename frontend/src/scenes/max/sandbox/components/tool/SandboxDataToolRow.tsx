import { type PropsWithChildren } from 'react'

import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolRow } from './SandboxToolRow'
import { resolveToolRowChrome } from './toolRowShared'

/**
 * Shared shell for the data-tool adapters (insight, dashboard, recordings, query, error tracking,
 * notebook). Renders the registry icon + tool title as the header and the adapter's visualization as
 * an expanded-by-default body — keeping data tools visually consistent with the per-tool cards while
 * each adapter keeps its own lazy chunk. `boxed={false}` because the visualization brings its own frame.
 */
export function SandboxDataToolRow({ children, ...props }: PropsWithChildren<SandboxToolRendererProps>): JSX.Element {
    const { message, icon, displayName } = props
    const chrome = resolveToolRowChrome(props)

    return (
        <SandboxToolRow
            icon={icon}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            defaultOpen
            boxed={false}
            content={children}
            debugDetails={chrome.debugDetails}
        >
            {message.title || displayName || 'Tool'}
        </SandboxToolRow>
    )
}
