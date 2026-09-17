import type { ReactNode } from 'react'

import { LemonCollapse, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import {
    type AITriage,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageStatusLabel,
    aiTriageTicketTypeDescription,
    aiTriageTicketTypeLabel,
} from '../../types'

interface AIPanelProps {
    aiTriage?: AITriage
}

function AITriageHeaderTag({ aiTriage }: { aiTriage?: AITriage }): JSX.Element | null {
    if (!aiTriage?.status) {
        return null
    }
    if (aiTriage.status === 'in_progress') {
        return <Spinner className="text-sm ml-1" />
    }
    if (aiTriage.result) {
        return (
            <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small" className="ml-1">
                {aiTriageResultLabel[aiTriage.result]}
            </LemonTag>
        )
    }
    return null
}

function AITriageRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between">
            <span className="text-muted-alt">{label}</span>
            {children}
        </div>
    )
}

function maybeTriageRow(
    label: string,
    children: ReactNode | null | undefined | false
): { label: string; children: ReactNode }[] {
    return children ? [{ label, children }] : []
}

function AITriageDetails({ aiTriage }: { aiTriage: AITriage }): JSX.Element {
    const rows = [
        ...maybeTriageRow(
            'Status',
            aiTriage.status ? <span>{aiTriageStatusLabel[aiTriage.status] ?? aiTriage.status}</span> : null
        ),
        ...maybeTriageRow(
            'Result',
            aiTriage.result ? (
                <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small">
                    {aiTriageResultLabel[aiTriage.result]}
                </LemonTag>
            ) : null
        ),
        ...maybeTriageRow(
            'Ticket type',
            aiTriage.ticket_type ? (
                <Tooltip title={aiTriageTicketTypeDescription[aiTriage.ticket_type]}>
                    <LemonTag size="small">
                        {aiTriageTicketTypeLabel[aiTriage.ticket_type] ?? aiTriage.ticket_type}
                    </LemonTag>
                </Tooltip>
            ) : null
        ),
        ...maybeTriageRow(
            'Confidence',
            aiTriage.confidence != null ? <span>{(aiTriage.confidence * 100).toFixed(0)}%</span> : null
        ),
        ...maybeTriageRow('Attempts', aiTriage.attempts != null ? <span>{aiTriage.attempts}</span> : null),
        ...maybeTriageRow(
            'Needs diagnostics',
            aiTriage.needs_diagnostics != null ? <span>{aiTriage.needs_diagnostics ? 'Yes' : 'No'}</span> : null
        ),
        ...maybeTriageRow(
            'Diagnostics allowed',
            aiTriage.diagnostics_allowed != null ? <span>{aiTriage.diagnostics_allowed ? 'Yes' : 'No'}</span> : null
        ),
        ...maybeTriageRow('Started', aiTriage.started_at ? <TZLabel time={aiTriage.started_at} /> : null),
        ...maybeTriageRow('Finished', aiTriage.finished_at ? <TZLabel time={aiTriage.finished_at} /> : null),
    ]

    return (
        <div className="space-y-2 text-xs">
            {rows.map(({ label, children }) => (
                <AITriageRow key={label} label={label}>
                    {children}
                </AITriageRow>
            ))}
        </div>
    )
}

export function AIPanel({ aiTriage }: AIPanelProps): JSX.Element {
    const hasData = Boolean(aiTriage?.status)

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ai_triage',
                    header: (
                        <span className="flex items-center">
                            AI triage
                            <AITriageHeaderTag aiTriage={aiTriage} />
                        </span>
                    ),
                    content:
                        hasData && aiTriage ? (
                            <AITriageDetails aiTriage={aiTriage} />
                        ) : (
                            <div className="text-muted-alt text-xs">AI has not processed this ticket yet.</div>
                        ),
                },
            ]}
        />
    )
}
