import React from 'react'

import { IconBug, IconCalendar } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ArtifactMessage, ErrorTrackingFiltersArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { DateRange } from '~/queries/schema/schema-general'

import { MessageStatus } from './maxLogic'
import { MessageTemplate } from './messages/MessageTemplate'

interface ErrorTrackingFiltersArtifactAnswerProps {
    message: ArtifactMessage & { status?: MessageStatus }
    content: ErrorTrackingFiltersArtifactContent
    status?: MessageStatus
}

function formatDateRange(dateRange: DateRange | undefined): string | null {
    if (!dateRange) {
        return null
    }
    const { date_from, date_to } = dateRange

    if (!date_from && !date_to) {
        return null
    }

    // Handle relative dates like "-7d", "-30d"
    if (date_from?.startsWith('-') && !date_to) {
        const match = date_from.match(/^-(\d+)([dhwmy])$/)
        if (match) {
            const [, num, unit] = match
            const unitNames: Record<string, string> = {
                d: 'day',
                h: 'hour',
                w: 'week',
                m: 'month',
                y: 'year',
            }
            const unitName = unitNames[unit] || unit
            return `Last ${num} ${unitName}${parseInt(num) > 1 ? 's' : ''}`
        }
        return `From ${date_from}`
    }

    if (date_from && date_to) {
        return `${date_from} to ${date_to}`
    }

    if (date_from) {
        return `From ${date_from}`
    }

    if (date_to) {
        return `Until ${date_to}`
    }

    return null
}

export const ErrorTrackingFiltersArtifactAnswer = React.memo(function ErrorTrackingFiltersArtifactAnswer({
    content,
    status,
}: ErrorTrackingFiltersArtifactAnswerProps): JSX.Element | null {
    if (status !== 'completed') {
        return null
    }

    const filters = content.filters || {}
    const filterStatus = filters.status as string | undefined
    const searchQuery = filters.searchQuery as string | undefined
    const dateRange = filters.dateRange as DateRange | undefined

    // Build URL params for error tracking page
    const urlParams: Record<string, unknown> = {}
    if (filterStatus) {
        urlParams.status = filterStatus
    }
    if (searchQuery) {
        urlParams.searchQuery = searchQuery
    }
    if (dateRange) {
        urlParams.dateRange = dateRange
    }

    const errorTrackingUrl = urls.errorTracking(urlParams)

    // Format date range for display
    const dateRangeDisplay = formatDateRange(dateRange)

    // Check if we have any filters to display
    const hasFilters = filterStatus || searchQuery || dateRangeDisplay

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    <IconBug className="text-lg shrink-0" />
                    <span className="font-medium truncate">Error tracking filters</span>
                </div>
                <LemonButton
                    to={errorTrackingUrl}
                    icon={<IconOpenInNew />}
                    size="xsmall"
                    type="secondary"
                    tooltip="Open in Error tracking"
                >
                    Open
                </LemonButton>
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-2">
                {filterStatus && (
                    <LemonTag
                        type={filterStatus === 'active' ? 'danger' : filterStatus === 'resolved' ? 'success' : 'muted'}
                    >
                        {filterStatus}
                    </LemonTag>
                )}
                {searchQuery && (
                    <LemonTag type="default">
                        <span className="text-muted-alt mr-1">Search:</span>
                        {searchQuery}
                    </LemonTag>
                )}
                {dateRangeDisplay && (
                    <LemonTag type="highlight" icon={<IconCalendar />}>
                        {dateRangeDisplay}
                    </LemonTag>
                )}
                {!hasFilters && <span className="text-muted text-sm">All issues</span>}
            </div>
        </MessageTemplate>
    )
})
