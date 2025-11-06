import { useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { SessionData, sessionProfileLogic } from '../sessionProfileLogic'

interface DetailRowProps {
    label: string
    value: React.ReactNode
    className?: string
}

function DetailRow({ label, value, className }: DetailRowProps): JSX.Element {
    return (
        <div className={`flex gap-2 ${className || ''}`}>
            <span className="text-secondary min-w-32">{label}:</span>
            <span className="truncate">{value}</span>
        </div>
    )
}

interface DetailSectionProps {
    title: string
    children: React.ReactNode
    defaultExpanded?: boolean
}

function DetailSection({ title, children, defaultExpanded = true }: DetailSectionProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded)

    return (
        <div className="border-t border-border">
            <div
                className="flex items-center justify-between h-10 px-4 cursor-pointer hover:bg-surface-primary"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <h4 className="text-sm font-semibold">{title}</h4>
                <LemonButton
                    icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                    size="small"
                    noPadding
                    onClick={(e) => {
                        e.stopPropagation()
                        setIsExpanded(!isExpanded)
                    }}
                />
            </div>
            {isExpanded && <div className="px-4 pb-4 space-y-2">{children}</div>}
        </div>
    )
}

export interface SessionDetailsCardProps {
    sessionData: SessionData | null
    isLoading?: boolean
}

export function SessionDetailsCard(): JSX.Element | null {
    const { sessionData, isInitialLoading, supportTicketEvents } = useValues(sessionProfileLogic)

    if (!sessionData || isInitialLoading) {
        return null
    }

    const hasAttribution =
        sessionData.entry_utm_source ||
        sessionData.entry_utm_campaign ||
        sessionData.entry_utm_medium ||
        sessionData.entry_referring_domain

    const hasUrls =
        sessionData.entry_current_url ||
        sessionData.end_current_url ||
        sessionData.last_external_click_url ||
        (sessionData.urls && sessionData.urls.length > 0)

    const hasSupportTickets = supportTicketEvents.length > 0

    return (
        <LemonCard className="overflow-hidden" hoverEffect={false}>
            <DetailSection title="Session Properties" defaultExpanded={true}>
                {sessionData.channel_type && (
                    <DetailRow label="Channel type" value={<LemonTag>{sessionData.channel_type}</LemonTag>} />
                )}
                <DetailRow
                    label="Is bounce"
                    value={
                        <LemonTag type={sessionData.is_bounce ? 'warning' : 'success'}>
                            {sessionData.is_bounce ? 'Yes' : 'No'}
                        </LemonTag>
                    }
                />
                {sessionData.entry_hostname && <DetailRow label="Entry hostname" value={sessionData.entry_hostname} />}
                {sessionData.entry_pathname && <DetailRow label="Entry pathname" value={sessionData.entry_pathname} />}
            </DetailSection>

            {hasAttribution && (
                <DetailSection title="Attribution" defaultExpanded={false}>
                    {sessionData.entry_referring_domain && (
                        <DetailRow label="Referring domain" value={sessionData.entry_referring_domain} />
                    )}
                    {sessionData.entry_utm_source && (
                        <DetailRow label="UTM source" value={sessionData.entry_utm_source} />
                    )}
                    {sessionData.entry_utm_campaign && (
                        <DetailRow label="UTM campaign" value={sessionData.entry_utm_campaign} />
                    )}
                    {sessionData.entry_utm_medium && (
                        <DetailRow label="UTM medium" value={sessionData.entry_utm_medium} />
                    )}
                </DetailSection>
            )}

            {hasUrls && (
                <DetailSection title="URLs" defaultExpanded={false}>
                    {sessionData.entry_current_url && (
                        <DetailRow
                            label="Entry URL"
                            value={
                                <Link to={sessionData.entry_current_url} target="_blank" className="truncate block">
                                    {sessionData.entry_current_url}
                                </Link>
                            }
                        />
                    )}
                    {sessionData.end_current_url && (
                        <DetailRow
                            label="Exit URL"
                            value={
                                <Link to={sessionData.end_current_url} target="_blank" className="truncate block">
                                    {sessionData.end_current_url}
                                </Link>
                            }
                        />
                    )}
                    {sessionData.last_external_click_url && (
                        <DetailRow
                            label="Last external click"
                            value={
                                <Link
                                    to={sessionData.last_external_click_url}
                                    target="_blank"
                                    className="truncate block"
                                >
                                    {sessionData.last_external_click_url}
                                </Link>
                            }
                        />
                    )}
                    {sessionData.urls && sessionData.urls.length > 0 && (
                        <div className="flex flex-col gap-2">
                            <div className="flex gap-2">
                                <span className="text-secondary min-w-32">All URLs ({sessionData.urls.length}):</span>
                            </div>
                            <div className="ml-32 space-y-1 max-h-60 overflow-y-auto">
                                {sessionData.urls.map((url, index) => (
                                    <div key={index} className="text-xs truncate">
                                        <Link to={url} target="_blank">
                                            {index + 1}. {url}
                                        </Link>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </DetailSection>
            )}

            {hasSupportTickets && (
                <DetailSection title="Support tickets" defaultExpanded={false}>
                    {supportTicketEvents.map((event, index) => {
                        const ticketId = event.properties?.zendesk_ticket_id
                        const zendeskUrl = ticketId ? `https://posthoghelp.zendesk.com/agent/tickets/${ticketId}` : null

                        return (
                            <div key={event.id} className="flex flex-col gap-1">
                                {index > 0 && <LemonDivider className="my-2" />}
                                <div className="flex gap-2 items-center">
                                    <span className="text-secondary min-w-32">
                                        <TZLabel time={event.timestamp} formatDate="MMM DD, h:mm A" />:
                                    </span>
                                    <div className="flex gap-2 items-center">
                                        {zendeskUrl ? (
                                            <Link to={zendeskUrl} target="_blank">
                                                Ticket #{ticketId}
                                            </Link>
                                        ) : (
                                            <span className="text-muted-alt">No ticket ID</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </DetailSection>
            )}
        </LemonCard>
    )
}
