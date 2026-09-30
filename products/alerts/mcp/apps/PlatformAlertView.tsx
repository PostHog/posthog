import { type ReactElement, type ReactNode } from 'react'

import { DataTable, type DataTableColumn, DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export type PlatformAlertState = 'not_firing' | 'firing' | 'errored' | 'snoozed' | 'broken'

export interface PlatformAlertGroupData {
    id: string
    grouping_key: string
    state: PlatformAlertState
    firing_started_at: string | null
    last_notified_at: string | null
    snooze_until: string | null
}

export interface PlatformAlertData {
    id: string
    name: string
    enabled: boolean
    source_kind: string
    threshold_count: number
    threshold_operator: string
    window_minutes: number
    check_interval_minutes: number
    evaluation_periods: number
    datapoints_to_alarm: number
    next_check_at: string | null
    consecutive_failures: number
    alerts: PlatformAlertGroupData[]
    _posthogUrl?: string
}

const STATE_BADGES: Record<
    PlatformAlertState,
    { label: string; variant: 'success' | 'destructive' | 'warning' | 'default' }
> = {
    not_firing: { label: 'OK', variant: 'success' },
    firing: { label: 'Firing', variant: 'destructive' },
    errored: { label: 'Errored', variant: 'warning' },
    snoozed: { label: 'Snoozed', variant: 'default' },
    broken: { label: 'Broken', variant: 'destructive' },
}

export function PlatformAlertStateBadge({ state }: { state: PlatformAlertState }): ReactElement {
    const badge = STATE_BADGES[state] ?? { label: state, variant: 'default' }
    return <Badge variant={badge.variant}>{badge.label}</Badge>
}

export function summarizePlatformAlert(alert: PlatformAlertData): ReactElement {
    if (!alert.enabled) {
        return <Badge>Disabled</Badge>
    }
    const firing = alert.alerts.filter((group) => group.state === 'firing').length
    if (alert.alerts.length > 1) {
        return firing > 0 ? (
            <Badge variant="destructive">
                {firing} of {alert.alerts.length} firing
            </Badge>
        ) : (
            <Badge variant="success">OK</Badge>
        )
    }
    return <PlatformAlertStateBadge state={alert.alerts[0]?.state ?? 'not_firing'} />
}

function optionalTime(value: string | null, fallback: string): string {
    return value ? formatDate(value, true) : fallback
}

// Platform alerts keep their state while snoozed; only the notification is held.
function snoozedUntil(group: PlatformAlertGroupData): string | null {
    return group.snooze_until && new Date(group.snooze_until) > new Date() ? group.snooze_until : null
}

const GROUP_COLUMNS: DataTableColumn<PlatformAlertGroupData>[] = [
    {
        key: 'grouping_key',
        header: 'Group',
        sortable: true,
        render: (row): ReactNode =>
            row.grouping_key ? (
                <span className="font-mono text-xs">{row.grouping_key}</span>
            ) : (
                <span className="text-muted-foreground">Ungrouped</span>
            ),
    },
    {
        key: 'state',
        header: 'State',
        sortable: true,
        render: (row): ReactNode => {
            const snoozed = snoozedUntil(row)
            return (
                <div className="flex items-center gap-2 flex-wrap">
                    <PlatformAlertStateBadge state={row.state} />
                    {snoozed && (
                        <span className="text-muted-foreground text-xs">Snoozed until {formatDate(snoozed, true)}</span>
                    )}
                </div>
            )
        },
    },
    {
        key: 'firing_started_at',
        header: 'Firing since',
        render: (row): ReactNode => (
            <span className="text-muted-foreground text-xs">{optionalTime(row.firing_started_at, 'Not firing')}</span>
        ),
    },
    {
        key: 'last_notified_at',
        header: 'Last notified',
        render: (row): ReactNode => (
            <span className="text-muted-foreground text-xs">{optionalTime(row.last_notified_at, 'Never')}</span>
        ),
    },
]

export function PlatformAlertView({ data }: { data: PlatformAlertData }): ReactElement {
    const operator = data.threshold_operator === 'below' ? 'Below' : 'Above'

    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-lg font-semibold break-all">{data.name}</span>
                    {summarizePlatformAlert(data)}
                    <Badge>{data.source_kind}</Badge>
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                {
                                    label: 'Condition',
                                    value: `${operator} ${data.threshold_count} in ${data.window_minutes} min`,
                                },
                                {
                                    label: 'Fires after',
                                    value: `${data.datapoints_to_alarm} of ${data.evaluation_periods} checks`,
                                },
                                { label: 'Checks', value: `Every ${data.check_interval_minutes} min` },
                                { label: 'Next check', value: optionalTime(data.next_check_at, 'Not scheduled') },
                                { label: 'Failed checks in a row', value: String(data.consecutive_failures) },
                            ]}
                        />
                    </CardContent>
                </Card>

                <DataTable<PlatformAlertGroupData>
                    columns={GROUP_COLUMNS}
                    data={data.alerts}
                    pageSize={20}
                    defaultSort={{ key: 'state', direction: 'asc' }}
                    emptyMessage="This alert has not been checked yet"
                />
            </div>
        </div>
    )
}
