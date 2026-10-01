import { ReactNode } from 'react'

import { IconWarning } from '@posthog/icons'

/** A problem with saving, shown above the library or inspector with the actions that resolve it. */
export function CanvasBlocksNotice({
    tone,
    title,
    detail,
    children,
}: {
    tone: 'error' | 'warning'
    title: string
    detail: string
    children: ReactNode
}): JSX.Element {
    return (
        <div
            className={`flex flex-col gap-2 border-b border-border px-3 py-2.5 ${tone === 'error' ? 'bg-destructive' : 'bg-warning'}`}
            data-attr={`canvas-blocks-notice-${tone}`}
        >
            <div className="flex items-start gap-2">
                <IconWarning
                    className={`mt-px shrink-0 ${tone === 'error' ? 'text-destructive-foreground' : 'text-warning-foreground'}`}
                />
                <div className="min-w-0 text-xs leading-snug">
                    <div className="font-medium text-foreground">{title}</div>
                    <div className="break-words text-muted-foreground">{detail}</div>
                </div>
            </div>
            <div className="flex flex-wrap gap-1.5 pl-5">{children}</div>
        </div>
    )
}
