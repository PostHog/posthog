import { ReactNode } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'
import { TraceCopyButton, TraceCopyButtonProps } from './TraceCopyButton'
import { TraceExportButton, TraceExportButtonProps } from './TraceExportButton'
import { TraceSearchBox, TraceSearchBoxProps } from './TraceSearchBox'
import { TraceStatusBadge } from './TraceStatusBadge'

export interface TraceHeaderProps {
    name: string
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
        <header className="flex flex-wrap items-center gap-2">
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
            <h1 className="m-0 min-w-0 truncate text-lg font-semibold">{name}</h1>
            <TraceStatusBadge hasError={hasError} />
            <div className="ml-auto flex min-w-0 flex-wrap items-center gap-2">
                {search ? <TraceSearchBox {...search} /> : null}
                {actions}
                {copyAction || exportAction ? (
                    <div className="flex items-center gap-1">
                        {copyAction ? <TraceCopyButton {...copyAction} /> : null}
                        {exportAction ? <TraceExportButton {...exportAction} /> : null}
                    </div>
                ) : null}
            </div>
        </header>
    )
}
