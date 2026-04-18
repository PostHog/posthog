import { useMemo } from 'react'

import { IconNotebook } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import type { LemonTableColumn, LemonTagType } from '@posthog/lemon-ui'

import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'

import type { AlertCheck, AlertType, InvestigationVerdict } from '../types'

const VERDICT_TAG: Record<InvestigationVerdict, { label: string; type: LemonTagType; tooltip: string }> = {
    true_positive: {
        label: 'True positive',
        type: 'danger',
        tooltip: 'Agent thinks this is a real anomaly worth looking at.',
    },
    false_positive: {
        label: 'False positive',
        type: 'muted',
        tooltip: 'Agent thinks this was a data/release artifact, not a real anomaly.',
    },
    inconclusive: {
        label: 'Inconclusive',
        type: 'warning',
        tooltip: 'Agent could not reach a confident conclusion from the available data.',
    },
}

function VerdictTag({ verdict }: { verdict: InvestigationVerdict }): JSX.Element {
    const cfg = VERDICT_TAG[verdict]
    return (
        <Tooltip title={cfg.tooltip}>
            <LemonTag type={cfg.type} size="small">
                {cfg.label}
            </LemonTag>
        </Tooltip>
    )
}

function InvestigationCell({ check }: { check: AlertCheck }): JSX.Element {
    const status = check.investigation_status
    const shortId = check.investigation_notebook_short_id
    const summary = check.investigation_summary?.trim() || null
    const verdict = check.investigation_verdict ?? null
    const suppressed = !!check.notification_suppressed_by_agent

    if (status === 'done' && shortId) {
        return (
            <div className="flex flex-col gap-1.5 items-start max-w-md w-fit ml-auto text-left">
                {suppressed && (
                    <Tooltip title="The investigation agent concluded this fire wasn't worth notifying about, so we didn't send an email / Slack / webhook for it.">
                        <LemonTag type="muted" size="small">
                            Notification suppressed
                        </LemonTag>
                    </Tooltip>
                )}
                {(verdict || summary) && (
                    <div className="flex items-start gap-1.5">
                        {verdict && <VerdictTag verdict={verdict} />}
                        {summary && <SummaryText summary={summary} leadingDash={!!verdict} />}
                    </div>
                )}
                <LemonButton type="secondary" size="xsmall" to={`/notebooks/${shortId}`} icon={<IconNotebook />}>
                    View notebook
                </LemonButton>
            </div>
        )
    }
    if (status === 'running' || status === 'pending') {
        return (
            <span className="inline-flex items-center gap-1 text-secondary">
                <Spinner textColored /> Running
            </span>
        )
    }
    if (status === 'failed') {
        return (
            <Tooltip title="The investigation agent could not complete. See server logs for details.">
                <span className="text-danger">Failed</span>
            </Tooltip>
        )
    }
    if (status === 'skipped') {
        return (
            <Tooltip title="Skipped because another investigation ran for this alert within the last hour.">
                <span className="text-secondary">Skipped</span>
            </Tooltip>
        )
    }
    return <span className="text-secondary">—</span>
}

function SummaryText({ summary, leadingDash = false }: { summary: string; leadingDash?: boolean }): JSX.Element {
    // Line-clamp adapts to cell width / font size, unlike a fixed char budget.
    // Full summary shows on hover via the tooltip.
    return (
        <Tooltip title={summary}>
            <span className="text-secondary text-sm leading-normal line-clamp-2">
                {leadingDash ? `— ${summary}` : summary}
            </span>
        </Tooltip>
    )
}

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    const isAnomalyDetection = !!alert.detector_config
    const investigationAgentEnabled = isAnomalyDetection && !!alert.investigation_agent_enabled

    const checkHistoryColumns = useMemo((): LemonTableColumn<AlertCheck, keyof AlertCheck | undefined>[] => {
        const columns: LemonTableColumn<AlertCheck, keyof AlertCheck | undefined>[] = [
            {
                title: 'Status',
                key: 'state',
                render: (_value, check) => check.state,
            },
            {
                title: 'Time',
                key: 'created_at',
                align: 'right',
                render: (_value, check) => <TZLabel time={check.created_at} />,
            },
            {
                title: 'Value',
                key: 'calculated_value',
                align: 'right',
                render: (_value, check) => check.calculated_value ?? '—',
            },
        ]
        if (isAnomalyDetection) {
            columns.push({
                title: 'Score',
                align: 'right',
                render: (_value, check) => {
                    const scores = check.anomaly_scores
                    const lastScore = scores?.length ? scores[scores.length - 1] : null
                    return lastScore != null ? lastScore.toFixed(3) : '—'
                },
            })
        }
        if (investigationAgentEnabled) {
            columns.push({
                title: 'Investigation',
                align: 'right',
                render: (_value, check) => <InvestigationCell check={check} />,
            })
        }
        columns.push({
            title: 'Targets notified',
            key: 'targets_notified',
            align: 'right',
            render: (_value, check) => (check.targets_notified ? 'Yes' : 'No'),
        })
        return columns
    }, [isAnomalyDetection, investigationAgentEnabled])

    if (!alert.checks || alert.checks.length === 0) {
        return null
    }

    return (
        <div className="mt-10 space-y-2">
            <div className="flex flex-row gap-2 items-center">
                <h3 className="m-0">Current status: </h3>
                <AlertStateIndicator alert={alert} />
                <h3 className="m-0">
                    {alert.snoozed_until && ` until ${formatDate(dayjs(alert?.snoozed_until), 'MMM D, HH:mm')}`}
                </h3>
            </div>
            <LemonTable
                dataSource={alert.checks}
                columns={checkHistoryColumns}
                rowKey="id"
                size="small"
                embedded
                uppercaseHeader={false}
            />
        </div>
    )
}
