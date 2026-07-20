import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import {
    AlertEvaluationHistoryChart,
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'

import { formatBillingValue } from './billingAlertDisplay'
import { billingAlertHistoryLogic } from './billingAlertHistoryLogic'
import type { BillingAlertConfigurationApi, BillingAlertEventApi } from './generated/api.schemas'

export function eventValue(alert: BillingAlertConfigurationApi, event: BillingAlertEventApi): number | null {
    const value =
        alert.threshold_type === 'relative_increase'
            ? event.relative_delta_percentage
            : alert.threshold_type === 'absolute_increase'
              ? event.absolute_delta
              : event.current_value
    if (value === null || value === undefined) {
        return null
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
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
    const value = eventValue(alert, event)
    if (value === null) {
        return false
    }
    const threshold = Number(
        alert.threshold_type === 'relative_increase' ? alert.threshold_percentage : alert.threshold_value
    )
    return Number.isFinite(threshold) && value >= threshold
}

function chartThreshold(alert: BillingAlertConfigurationApi): AlertEvaluationThreshold[] {
    const value = Number(
        alert.threshold_type === 'relative_increase' ? alert.threshold_percentage : alert.threshold_value
    )
    if (!Number.isFinite(value)) {
        return []
    }
    const label =
        alert.threshold_type === 'relative_increase'
            ? `${value}% increase`
            : formatBillingValue(value, alert.metric, alert.currency)
    return [{ direction: 'upper', value, label }]
}

function chartPoints(
    alert: BillingAlertConfigurationApi,
    events: BillingAlertEventApi[]
): AlertEvaluationHistoryPoint[] {
    return events
        .map((event) => ({ event, value: eventValue(alert, event) }))
        .filter((item): item is { event: BillingAlertEventApi; value: number } => item.value !== null)
        .sort((left, right) => left.event.created_at.localeCompare(right.event.created_at))
        .map(({ event, value }) => ({
            label: dayjs(event.created_at).format('MMM D, HH:mm'),
            value,
            firedAtTime: event.state_after === 'firing',
            wouldFireUnderCurrentConfiguration: wouldFire(alert, event),
        }))
}

function eventTag(event: BillingAlertEventApi): { label: string; type: LemonTagType } {
    if (event.kind === 'firing') {
        return { label: 'Fired', type: 'danger' }
    }
    if (event.kind === 'resolved') {
        return { label: 'Resolved', type: 'success' }
    }
    if (event.kind === 'errored' || event.kind === 'broken_config') {
        return { label: event.kind === 'errored' ? 'Errored' : 'Broken', type: 'warning' }
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
    const { eventsPage, eventsPageLoading } = useValues(billingAlertHistoryLogic)
    const { loadMoreEvents } = useActions(billingAlertHistoryLogic)
    const points = chartPoints(alert, eventsPage.results.slice(0, 50))
    const valueLabel =
        alert.threshold_type === 'relative_increase'
            ? 'Increase'
            : alert.threshold_type === 'absolute_increase'
              ? 'Increase over baseline'
              : 'Spend'
    const formatter = (value: number): string =>
        alert.threshold_type === 'relative_increase'
            ? `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`
            : formatBillingValue(value, alert.metric, alert.currency)
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
                        valueLabel={valueLabel}
                        thresholds={chartThreshold(alert)}
                        historyLimit={50}
                        evaluationsTotal={eventsPage.count}
                        evaluationNoun="evaluation"
                        tableAvailable
                        formatValue={formatter}
                    />
                ) : null}
                <LemonTable
                    columns={columns}
                    dataSource={eventsPage.results}
                    rowKey="id"
                    loading={eventsPageLoading}
                    size="small"
                    emptyState="No evaluations yet."
                />
                {eventsPage.next ? (
                    <div className="flex justify-center">
                        <LemonButton type="secondary" loading={eventsPageLoading} onClick={loadMoreEvents}>
                            Load older evaluations
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        </AlertEditorSection>
    )
}
