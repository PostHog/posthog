import type { ReactNode } from 'react'

import { LemonCollapse, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import {
    type AITriage,
    type AITriageSource,
    aiTriageBlockerLabel,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageStatusLabel,
    aiTriageTicketTypeDescription,
    aiTriageTicketTypeLabel,
    aiTriageVerdictLabel,
    ticketListAiTriage,
} from '../../types'

interface AIPanelProps {
    aiTriage?: AITriage
}

function AITriageHeaderTag({ aiTriage }: { aiTriage?: AITriage }): JSX.Element | null {
    const display = ticketListAiTriage(aiTriage)
    if (display.kind === 'processing') {
        return <Spinner className="text-sm ml-1" />
    }
    if (display.kind === 'tag') {
        return (
            <LemonTag type={display.tagType} size="small" className="ml-1">
                {display.label}
            </LemonTag>
        )
    }
    return null
}

function AITriageRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between gap-2 min-w-0">
            <span className="text-muted-alt shrink-0">{label}</span>
            <span className="min-w-0 text-right break-words">{children}</span>
        </div>
    )
}

function maybeTriageRow(
    label: string,
    children: ReactNode | null | undefined | false
): { label: string; children: ReactNode }[] {
    return children ? [{ label, children }] : []
}

function AITriageBulletList({ items }: { items: string[] }): JSX.Element {
    return (
        <ul className="m-0 pl-4 space-y-0.5 break-words">
            {items.map((item) => (
                <li key={item}>{item}</li>
            ))}
        </ul>
    )
}

function AISourceItem({ source }: { source: AITriageSource }): JSX.Element {
    const title = source.title || source.ref
    const name =
        source.source_id != null ? (
            <Link to={urls.businessKnowledgeSource(source.source_id)} className="truncate">
                {title}
            </Link>
        ) : source.url ? (
            <Link to={source.url} target="_blank" className="truncate">
                {title}
            </Link>
        ) : (
            <span className="truncate">{title}</span>
        )

    return (
        <li className="flex flex-col min-w-0 gap-0.5">
            <span className="flex items-center gap-1 min-w-0">
                {name}
                {source.is_generated ? (
                    <LemonTag type="highlight" size="small">
                        Learned
                    </LemonTag>
                ) : null}
            </span>
            {source.is_generated && source.learned_from_ticket_number != null ? (
                <Link
                    to={urls.supportTicketDetail(source.learned_from_ticket_number)}
                    className="text-xs text-muted truncate"
                >
                    Learned from ticket #{source.learned_from_ticket_number}
                </Link>
            ) : null}
        </li>
    )
}

function AITriageDetails({ aiTriage }: { aiTriage: AITriage }): JSX.Element {
    const unknowns = (aiTriage.unknowns ?? []).filter((item) => item.trim())
    const missing = (aiTriage.missing ?? []).filter((item) => item.trim())
    const sources = aiTriage.sources ?? []
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
            'Verdict',
            aiTriage.verdict ? <span>{aiTriageVerdictLabel[aiTriage.verdict] ?? aiTriage.verdict}</span> : null
        ),
        ...maybeTriageRow(
            'Blocker',
            aiTriage.blocker && aiTriage.blocker !== 'none' ? (
                <span>{aiTriageBlockerLabel[aiTriage.blocker] ?? aiTriage.blocker}</span>
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
        <div className="space-y-2 text-xs min-w-0">
            {rows.map(({ label, children }) => (
                <AITriageRow key={label} label={label}>
                    {children}
                </AITriageRow>
            ))}
            {aiTriage.investigation_summary?.trim() ? (
                <div className="min-w-0">
                    <div className="text-muted-alt">Investigation</div>
                    <p className="m-0 mt-0.5 whitespace-pre-wrap break-words">{aiTriage.investigation_summary}</p>
                </div>
            ) : null}
            {unknowns.length > 0 ? (
                <div className="min-w-0">
                    <div className="text-muted-alt">Still unknown</div>
                    <AITriageBulletList items={unknowns} />
                </div>
            ) : null}
            {missing.length > 0 ? (
                <div className="min-w-0">
                    <div className="text-muted-alt">Missing from knowledge</div>
                    <AITriageBulletList items={missing} />
                </div>
            ) : null}
            {sources.length > 0 ? (
                <div className="min-w-0">
                    <div className="text-muted-alt">Sources</div>
                    <ul className="m-0 mt-0.5 pl-0 list-none space-y-1">
                        {sources.map((source, index) => (
                            <AISourceItem key={`${source.ref}-${index}`} source={source} />
                        ))}
                    </ul>
                </div>
            ) : null}
        </div>
    )
}

export function AIPanel({ aiTriage }: AIPanelProps): JSX.Element {
    const hasData = Boolean(aiTriage?.status)

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey={hasData ? 'ai_triage' : undefined}
            panels={[
                {
                    key: 'ai_triage',
                    header: (
                        <span className="flex items-center min-w-0">
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
