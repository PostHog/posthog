import { useMemo } from 'react'

import { LemonTable } from '@posthog/lemon-ui'
import type { LemonTableColumn } from '@posthog/lemon-ui'

import { AlertStateIndicator } from 'lib/components/Alerts/views/ManageAlertsModal'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { formatDate } from 'lib/utils'

import type { AlertCheck, AlertType } from '../types'

export function AlertStateTable({ alert }: { alert: AlertType }): JSX.Element | null {
    const isAnomalyDetection = !!alert.detector_config

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
        columns.push({
            title: 'Targets notified',
            key: 'targets_notified',
            align: 'right',
            render: (_value, check) => (check.targets_notified ? 'Yes' : 'No'),
        })
        return columns
    }, [isAnomalyDetection])

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
