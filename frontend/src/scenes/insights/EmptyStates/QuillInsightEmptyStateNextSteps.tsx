import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { IconCalendar, IconLineGraph, IconPulse } from '@posthog/icons'
import { Button, EmptyContent, EmptyDescription, EmptyHeader } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { Dayjs } from 'lib/dayjs'
import { keyForInsightLogicProps } from 'lib/insights/sharedUtils'
import { revealSeriesFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { openInsightEditor } from 'products/product_analytics/frontend/insights/insightScene/openInsightEditor'

import { EmptyStateReason, rangeReaching } from './emptyStateReason'
import { insightEmptyStateLogic } from './insightEmptyStateLogic'
import { QuillInsightEmptyStateIcon } from './QuillInsightEmptyStateIcon'

const REASON_ICONS: Record<EmptyStateReason['kind'], JSX.Element> = {
    'never-sent': <IconPulse />,
    'last-seen-before': <IconCalendar />,
    'last-seen-after': <IconCalendar />,
    filtered: <IconLineGraph />,
    unknown: <IconLineGraph />,
}

function eventLabel(event: string): string {
    return getCoreFilterDefinition(event, TaxonomicFilterGroupType.Events)?.label ?? event
}

function formatDay(day: Dayjs): string {
    return day.format('D MMM YYYY')
}

/** Says why the insight came back empty and offers the change most likely to fill it. */
export function QuillInsightEmptyStateNextSteps({
    defaultDetail,
    icon,
    children,
}: {
    defaultDetail: ReactNode
    icon?: JSX.Element
    children: ReactNode
}): JSX.Element {
    const { insight, insightProps, canEditInsight } = useValues(insightLogic)
    const { dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange, updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { query, queryChanged } = useValues(insightDataLogic(insightProps))
    const { reason, hasInsightFilters, hasSeriesFilters } = useValues(insightEmptyStateLogic({ insightProps }))
    const { location } = useValues(router)

    const canEdit = !!insight.short_id && canEditInsight && !location.pathname.endsWith('/edit')

    let detail = defaultDetail
    let fix: JSX.Element | null = null
    switch (reason.kind) {
        case 'never-sent':
            detail =
                reason.events.length === 1
                    ? `${eventLabel(reason.events[0])} has never been sent to this project.`
                    : `None of these events has been sent to this project: ${reason.events.map(eventLabel).join(', ')}.`
            break
        case 'last-seen-before': {
            const range = rangeReaching(reason.lastSeen)
            detail = `${eventLabel(reason.event)} was last sent on ${formatDay(reason.lastSeen)}, before this date range.`
            fix = (
                <Button
                    variant="outline"
                    onClick={() => updateDateRange({ date_from: range.dateFrom, date_to: null }, true)}
                    data-attr="insight-empty-state-widen-date-range"
                >
                    {range.label}
                </Button>
            )
            break
        }
        case 'last-seen-after':
            detail = `${eventLabel(reason.event)} was last sent on ${formatDay(reason.lastSeen)}, after this date range.`
            fix = (
                <Button
                    variant="outline"
                    onClick={() => updateDateRange({ date_from: dateRange?.date_from, date_to: null }, true)}
                    data-attr="insight-empty-state-extend-to-today"
                >
                    Show up to today
                </Button>
            )
            break
        case 'filtered':
            detail = `${eventLabel(reason.event)} was sent in this date range, but ${hasInsightFilters ? 'the filters exclude it' : 'the filters on the series exclude it'}.`
            if (hasInsightFilters) {
                fix = (
                    <Button
                        variant="outline"
                        onClick={() => updateQuerySource({ properties: [], filterTestAccounts: false })}
                        data-attr="insight-empty-state-remove-filters"
                    >
                        Remove filters
                    </Button>
                )
            }
            break
    }

    return (
        <>
            <EmptyHeader>
                <QuillInsightEmptyStateIcon icon={icon ?? REASON_ICONS[reason.kind]} />
                {children}
                <EmptyDescription className="text-sm">{detail}</EmptyDescription>
            </EmptyHeader>
            {(fix || canEdit) && (
                <EmptyContent className="flex-row justify-center">
                    {fix}
                    {canEdit && (
                        <Button
                            variant="outline"
                            onClick={() => {
                                if (reason.kind === 'filtered' && hasSeriesFilters) {
                                    revealSeriesFilters(keyForInsightLogicProps('new')(insightProps))
                                }
                                openInsightEditor({
                                    query,
                                    insightShortId: insight.short_id,
                                    dashboardId: insightProps.dashboardId ?? null,
                                    queryChanged,
                                    enterEditMode: () => {},
                                })
                            }}
                            data-attr="insight-empty-state-edit"
                        >
                            Edit
                        </Button>
                    )}
                </EmptyContent>
            )}
        </>
    )
}
