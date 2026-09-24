import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import type { OsFrameStatus } from './osWindowFramesLogic'

export interface OsWindowFrameStatusProps {
    status: OsFrameStatus
    title: string
    onReload: () => void
}

/** What a window shows over its frame until the app in it has loaded. */
export function OsWindowFrameStatus({ status, title, onReload }: OsWindowFrameStatusProps): JSX.Element | null {
    if (status === 'ready') {
        return null
    }
    if (status === 'slow') {
        // A bar above the frame keeps an error page inside the frame visible and usable.
        return (
            <div
                className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-primary bg-surface-secondary px-3 py-1 text-xs"
                role="status"
                data-attr="os-window-frame-slow"
            >
                <span className="min-w-0 flex-1">{title} is taking longer than usual to load.</span>
                <LemonButton type="secondary" size="xsmall" onClick={onReload} data-attr="os-window-frame-reload">
                    Reload
                </LemonButton>
            </div>
        )
    }
    return (
        <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-surface-primary text-secondary"
            role="status"
            data-attr="os-window-frame-loading"
        >
            <Spinner className="text-3xl" />
            <span className="text-sm">Loading {title}</span>
        </div>
    )
}
