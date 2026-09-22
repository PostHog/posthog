import { BindLogic, useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import {
    AlertEvaluationHistoryChart,
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'

import { formatBillingValue, thresholdView } from './billingAlertDisplay'
import { billingAlertHistoryLogic, HISTORY_PAGE_SIZE } from './billingAlertHistoryLogic'
import type { BillingAlertConfigurationApi, BillingAlertEventApi } from './generated/api.schemas'

export function eventValue(alert: BillingAlertConfigurationApi, event: BillingAlertEventApi): number | null {
    return thresholdView(alert).pickEventValue(event)
}

export function wouldFire(alert: BillingAlertConfigurationApi, event: BillingAlertEventApi): boolean {
    if (event.current_value === null || event.current_value === undefined) {
        return false
    }
    const current = Number(event.current_value)
    const minimum = Number(alert.minimum_value ?? 0)
    if (!Number.isFinite(current) || current < minimum) {
        return false
    }
    const view = thresholdView(alert)
    const value = view.pickEventValue(event)
    if (value === null || view.thresholdValue === null) {
        return false
    }
    return value >= view.thresholdValue
}

function chartThreshold(alert: BillingAlertConfigurationApi): AlertEvaluationThreshold[] {
    const view = thresholdView(alert)
    if (view.thresholdValue === null) {
        return []
    }
    return [{ direction: 'upper', value: view.thresholdValue, label: view.thresholdLabel }]
}

export function historyPoint(
    alert: BillingAlertConfigurationApi,
    event: BillingAlertEventApi
): AlertEvaluationHistoryPoint | null {
    const value = eventValue(alert, event)
    if (value === null) {
        return null
    }
    return {
        label: dayjs(event.created_at).format('MMM D, HH:mm'),
        value,
        firedAtTime: event.kind === 'firing',
        wouldFireUnderCurrentConfiguration:
            event.configuration_revision === alert.configuration_revision ? wouldFire(alert, event) : null,
    }
}

function chartPoints(
    alert: BillingAlertConfigurationApi,
    events: BillingAlertEventApi[]
): AlertEvaluationHistoryPoint[] {
    return events
        .slice()
        .sort((left, right) => left.created_at.localeCompare(right.created_at))
        .map((event) => historyPoint(alert, event))
        .filter((point): point is AlertEvaluationHistoryPoint => point !== null)
}

function eventTag(event: BillingAlertEventApi): { label: string; type: LemonTagType } {
    if (event.kind === 'firing') {
        return { label: 'Fired', type: 'danger' }
    }
    if (event.kind === 'resolved') {
        return { label: 'Resolved', type: 'success' }
    }
    if (event.kind === 'errored' || event.kind === 'broken_config') {
        return { label: event.kind === 'errored' ? 'Errored' : 'Auto-disabled', type: 'warning' }
    }
    return { label: 'Check', type: 'default' }
}

export function BillingAlertHistory({ alert }: { alert: BillingAlertConfigurationApi }): JSX.Element {
    return (
        <BindLogic logic={billingAlertHistoryLogic} props={{ alertId: alert.id }}>
            <BillingAlertHistoryContent alert={alert} />
        </BindLogic>
    )
}

function BillingAlertHistoryContent({ alert }: { alert: BillingAlertConfigurationApi }): JSX.Element {
    const { currentPage, eventsPage, eventsPageLoading } = useValues(billingAlertHistoryLogic)
    const { loadMoreEvents, loadPreviousEvents } = useActions(billingAlertHistoryLogic)
    const view = thresholdView(alert)
    // The chart claims to show the most recent evaluations, so only render it from first-page data.
    const points = currentPage === 1 ? chartPoints(alert, eventsPage.results) : []
    const columns: LemonTableColumns<BillingAlertEventApi> = [
        {
            title: 'Event',
            render: (_, event) => {
                const tag = eventTag(event)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'When',
            render: (_, event) => <TZLabel time={event.created_at} formatDate="MMM D" formatTime="HH:mm:ss" />,
        },
        {
            title: 'Value',
            render: (_, event) => formatBillingValue(event.current_value, event.metric, alert.currency),
        },
        {
            title: 'Reason',
            render: (_, event) => <span className="text-xs text-secondary">{event.reason}</span>,
        },
    ]

    return (
        <AlertEditorSection title="History" description="Evaluations, transitions, errors, and notifications.">
            <div data-attr="billing-alert-history" className="space-y-4">
                {points.length > 0 ? (
                    <AlertEvaluationHistoryChart
                        points={points}
                        valueLabel={view.valueLabel}
                        thresholds={chartThreshold(alert)}
                        historyLimit={HISTORY_PAGE_SIZE}
                        evaluationsTotal={eventsPage.count}
                        evaluationNoun="evaluation"
                        tableAvailable
                        formatValue={view.format}
                    />
                ) : null}
                <LemonTable
                    columns={columns}
                    dataSource={eventsPage.results}
                    rowKey="id"
                    loading={eventsPageLoading}
                    size="small"
                    emptyState="No evaluations yet."
                    nouns={['evaluation', 'evaluations']}
                    pagination={{
                        controlled: true,
                        hideOnSinglePage: false,
                        currentPage,
                        pageSize: HISTORY_PAGE_SIZE,
                        entryCount: eventsPage.count,
                        onForward: eventsPage.next ? () => loadMoreEvents(undefined) : undefined,
                        onBackward: eventsPage.previous ? () => loadPreviousEvents(undefined) : undefined,
                    }}
                />
            </div>
        </AlertEditorSection>
    )
}
