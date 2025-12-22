import React from 'react'

import { IconBug, IconTrending } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import {
    ArtifactMessage,
    ErrorTrackingImpactArtifactContent,
    ErrorTrackingImpactSegment,
} from '~/queries/schema/schema-assistant-messages'

import { MessageStatus } from './maxLogic'
import { MessageTemplate } from './messages/MessageTemplate'

interface ErrorTrackingImpactArtifactAnswerProps {
    message: ArtifactMessage & { status?: MessageStatus }
    content: ErrorTrackingImpactArtifactContent
    status?: MessageStatus
}

function formatNumber(num: number): string {
    if (num >= 1000000) {
        return `${(num / 1000000).toFixed(1)}M`
    }
    if (num >= 1000) {
        return `${(num / 1000).toFixed(1)}K`
    }
    return num.toLocaleString()
}

function getTrendIcon(trend: string): JSX.Element | undefined {
    switch (trend) {
        case 'increasing':
            return <IconTrending className="text-danger rotate-0" />
        case 'decreasing':
            return <IconTrending className="text-success rotate-180" />
        default:
            return undefined
    }
}

function getTrendTagType(trend: string): 'danger' | 'success' | 'default' {
    switch (trend) {
        case 'increasing':
            return 'danger'
        case 'decreasing':
            return 'success'
        default:
            return 'default'
    }
}

export const ErrorTrackingImpactArtifactAnswer = React.memo(function ErrorTrackingImpactArtifactAnswer({
    content,
    status,
}: ErrorTrackingImpactArtifactAnswerProps): JSX.Element | null {
    if (status !== 'completed') {
        return null
    }

    const issueUrl = urls.errorTrackingIssue(content.issue_id)

    const trendText = content.trend_percentage
        ? `${content.trend} (${content.trend_percentage > 0 ? '+' : ''}${content.trend_percentage}%)`
        : content.trend

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    <IconBug className="text-lg shrink-0" />
                    <span className="font-medium truncate">{content.issue_name}</span>
                </div>
                <LemonButton to={issueUrl} icon={<IconOpenInNew />} size="xsmall" type="secondary" tooltip="Open issue">
                    Open
                </LemonButton>
            </div>

            {/* Main metrics */}
            <div className="flex flex-wrap items-center gap-3 mt-3">
                <Tooltip title="Total occurrences in the last 30 days">
                    <div className="flex flex-col items-center px-3 py-1 bg-bg-light rounded">
                        <span className="text-lg font-semibold">{formatNumber(content.occurrences)}</span>
                        <span className="text-xs text-muted">Occurrences</span>
                    </div>
                </Tooltip>
                <Tooltip title="Unique users affected">
                    <div className="flex flex-col items-center px-3 py-1 bg-bg-light rounded">
                        <span className="text-lg font-semibold">{formatNumber(content.users_affected)}</span>
                        <span className="text-xs text-muted">Users</span>
                    </div>
                </Tooltip>
                <Tooltip title="Sessions affected">
                    <div className="flex flex-col items-center px-3 py-1 bg-bg-light rounded">
                        <span className="text-lg font-semibold">{formatNumber(content.sessions_affected)}</span>
                        <span className="text-xs text-muted">Sessions</span>
                    </div>
                </Tooltip>
            </div>

            {/* Trend */}
            <div className="flex items-center gap-2 mt-3">
                <span className="text-sm text-muted">7-day trend:</span>
                <LemonTag type={getTrendTagType(content.trend)} icon={getTrendIcon(content.trend)}>
                    {trendText}
                </LemonTag>
            </div>

            {/* Top breakdowns */}
            {(content.top_browsers || content.top_os || content.top_urls) && (
                <div className="flex flex-col gap-2 mt-3 pt-3 border-t border-border">
                    {content.top_browsers && content.top_browsers.length > 0 && (
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs text-muted w-16">Browsers:</span>
                            {content.top_browsers.slice(0, 3).map((segment: ErrorTrackingImpactSegment) => (
                                <LemonTag key={segment.value} type="default" size="small">
                                    {segment.value} ({segment.percentage}%)
                                </LemonTag>
                            ))}
                        </div>
                    )}
                    {content.top_os && content.top_os.length > 0 && (
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs text-muted w-16">OS:</span>
                            {content.top_os.slice(0, 3).map((segment: ErrorTrackingImpactSegment) => (
                                <LemonTag key={segment.value} type="default" size="small">
                                    {segment.value} ({segment.percentage}%)
                                </LemonTag>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </MessageTemplate>
    )
})
