import { useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { SessionData } from '../sessionProfileLogic'

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

export function SessionDetailsCard({ sessionData, isLoading }: SessionDetailsCardProps): JSX.Element | null {
    if (!sessionData || isLoading) {
        return null
    }

    const hasAttribution =
        sessionData.entry_utm_source ||
        sessionData.entry_utm_campaign ||
        sessionData.entry_utm_medium ||
        sessionData.entry_referring_domain

    const hasUrls = sessionData.entry_current_url || sessionData.end_current_url || sessionData.last_external_click_url

    return (
        <LemonCard className="overflow-hidden">
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
                            value={<span className="truncate">{sessionData.entry_current_url}</span>}
                        />
                    )}
                    {sessionData.end_current_url && (
                        <DetailRow
                            label="Exit URL"
                            value={<span className="truncate">{sessionData.end_current_url}</span>}
                        />
                    )}
                    {sessionData.last_external_click_url && (
                        <DetailRow
                            label="Last external click"
                            value={<span className="truncate">{sessionData.last_external_click_url}</span>}
                        />
                    )}
                </DetailSection>
            )}
        </LemonCard>
    )
}
