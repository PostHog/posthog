import { ReactNode } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'
import { TraceCopyButton, TraceCopyButtonProps } from './TraceCopyButton'
import { TraceExportButton, TraceExportButtonProps } from './TraceExportButton'
import { TraceSearchBox, TraceSearchBoxProps } from './TraceSearchBox'
import { TraceStatusBadge } from './TraceStatusBadge'

export interface TraceHeaderProps {
    name: string | null
    hasError: boolean
    backLink: LabeledLink | null
    search?: TraceSearchBoxProps | null
    copyAction?: TraceCopyButtonProps
    exportAction?: TraceExportButtonProps
    actions?: ReactNode
}

export function TraceHeader({
    name,
    hasError,
    backLink,
    search = null,
    copyAction,
    exportAction,
    actions = null,
}: TraceHeaderProps): JSX.Element {
    return (
        <header className="@container">
            <div className="flex flex-col gap-2 @4xl:flex-row @4xl:items-center">
                <div className="flex min-w-0 items-center gap-2 @4xl:flex-1">
                    {backLink ? (
                        <LemonButton
                            size="small"
                            icon={<IconArrowLeft />}
                            to={backLink.href}
                            tooltip={backLink.label}
                            aria-label={backLink.label}
                            data-attr="trace-view-back"
                        />
                    ) : null}
                    <h1 className="m-0 min-w-0 truncate text-lg font-semibold">{name || 'Untitled trace'}</h1>
                    <TraceStatusBadge hasError={hasError} />
                </div>
                {/* Beside the title the search keeps its width; on a row of its own it takes whatever the buttons leave,
                    and on the narrowest headers it takes a whole line and the buttons sit below it. */}
                <div className="flex flex-wrap items-center gap-2 @xl:flex-nowrap">
                    {search ? (
                        <div className="w-full @xl:w-auto @xl:min-w-0 @xl:flex-1 @4xl:w-80 @4xl:flex-none">
                            <TraceSearchBox {...search} />
                        </div>
                    ) : null}
                    {actions}
                    {copyAction || exportAction ? (
                        <div className="flex items-center gap-1">
                            {copyAction ? <TraceCopyButton {...copyAction} /> : null}
                            {exportAction ? <TraceExportButton {...exportAction} /> : null}
                        </div>
                    ) : null}
                </div>
            </div>
        </header>
    )
}
