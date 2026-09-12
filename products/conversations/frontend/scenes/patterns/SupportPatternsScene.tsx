import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ScenesTabs } from '../../components/ScenesTabs'
import { TicketPatternSeverityTag } from '../../components/TicketPatterns/TicketPatternSeverityTag'
import { ticketPatternsLogic } from '../../components/TicketPatterns/ticketPatternsLogic'
import type { TicketPatternApi } from '../../generated/api.schemas'
import { type PatternStatusFilter, supportPatternsSceneLogic } from './supportPatternsSceneLogic'

export const scene: SceneExport = {
    component: SupportPatternsScene,
    logic: supportPatternsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
}

const STATUS_OPTIONS: { value: PatternStatusFilter; label: string }[] = [
    { value: 'open', label: 'Needs review' },
    { value: 'confirmed', label: 'Confirmed' },
    { value: 'dismissed', label: 'Dismissed' },
    { value: 'resolved', label: 'Resolved' },
    { value: 'all', label: 'All' },
]

const STATUS_LABEL: Record<TicketPatternApi['status'], string> = {
    open: 'Needs review',
    confirmed: 'Confirmed',
    dismissed: 'Dismissed',
    resolved: 'Resolved',
}

export function SupportPatternsScene(): JSX.Element {
    const { visiblePatterns, patternsLoading, statusFilter } = useValues(supportPatternsSceneLogic)
    const { setStatusFilter } = useActions(supportPatternsSceneLogic)
    const { patternsEnabled, inFlightIds } = useValues(ticketPatternsLogic)
    const { confirmPattern, dismissPattern } = useActions(ticketPatternsLogic)

    if (!patternsEnabled) {
        return <NotFound object="page" />
    }

    // The list endpoint admits a ticket viewer, but both transitions need editor, so a viewer would
    // otherwise get live buttons and a 403 they cannot act on.
    const decisionDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Ticket, AccessControlLevel.Editor) ?? undefined

    const columns: LemonTableColumns<TicketPatternApi> = [
        {
            title: 'Pattern',
            key: 'title',
            render: (_, pattern) => {
                const busy = inFlightIds.includes(pattern.id)
                return (
                    <div className="flex flex-col gap-1 min-w-0 py-1">
                        <div className="flex flex-wrap items-center gap-2 min-w-0">
                            <TicketPatternSeverityTag severity={pattern.severity} />
                            <span className="font-semibold truncate">{pattern.title}</span>
                            {statusFilter === 'all' ? <LemonTag>{STATUS_LABEL[pattern.status]}</LemonTag> : null}
                        </div>
                        {pattern.summary ? <span className="text-muted text-xs">{pattern.summary}</span> : null}
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                            <span translate="no">
                                {pattern.ticket_count} {pattern.ticket_count === 1 ? 'ticket' : 'tickets'} from{' '}
                                {pattern.requester_count} {pattern.requester_count === 1 ? 'customer' : 'customers'}
                            </span>
                            {pattern.first_ticket_at ? (
                                <span>
                                    first <TZLabel time={pattern.first_ticket_at} />
                                </span>
                            ) : null}
                            <span>
                                last <TZLabel time={pattern.last_seen_at} />
                            </span>
                        </div>
                        {pattern.status === 'open' ? (
                            <div className="flex flex-wrap gap-1 pt-1">
                                <LemonButton
                                    size="xsmall"
                                    type="primary"
                                    loading={busy}
                                    disabledReason={busy ? 'Saving' : decisionDisabledReason}
                                    onClick={() => confirmPattern(pattern.id)}
                                    data-attr="ticket-pattern-confirm"
                                >
                                    Confirm
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    loading={busy}
                                    disabledReason={busy ? 'Saving' : decisionDisabledReason}
                                    onClick={() => dismissPattern(pattern.id)}
                                    data-attr="ticket-pattern-dismiss"
                                >
                                    Not an issue
                                </LemonButton>
                            </div>
                        ) : null}
                    </div>
                )
            },
        },
    ]

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={statusFilter}
                    onChange={(value) => setStatusFilter(value as PatternStatusFilter)}
                    options={STATUS_OPTIONS}
                />
            </div>
            {!patternsLoading && visiblePatterns.length === 0 ? (
                <ProductIntroduction
                    thingName="pattern"
                    titleOverride={
                        statusFilter === 'open' ? 'No patterns need review' : 'No patterns match this filter'
                    }
                    description="A pattern opens when several different customers raise the same topic inside an hour. Detection runs every 15 minutes on the tickets in this project."
                    isEmpty
                    actionElementOverride={
                        <LemonButton type="secondary" to={urls.supportTickets()}>
                            Back to tickets
                        </LemonButton>
                    }
                />
            ) : (
                <LemonTable
                    dataSource={visiblePatterns}
                    columns={columns}
                    loading={patternsLoading}
                    rowKey="id"
                    expandable={{
                        rowExpandable: (pattern) => pattern.tickets.length > 0,
                        expandedRowRender: (pattern) => (
                            <ul className="p-2 flex flex-col gap-1">
                                {pattern.tickets.map((ticket) => (
                                    <li key={ticket.id} className="flex flex-wrap gap-2 items-baseline">
                                        <Link to={urls.supportTicketDetail(ticket.ticket_number)}>
                                            #{ticket.ticket_number}
                                        </Link>
                                        <span className="truncate">
                                            {ticket.email_subject || ticket.channel_source}
                                        </span>
                                        <TZLabel time={ticket.created_at} className="text-muted text-xs" />
                                    </li>
                                ))}
                            </ul>
                        ),
                    }}
                />
            )}
        </SceneContent>
    )
}
