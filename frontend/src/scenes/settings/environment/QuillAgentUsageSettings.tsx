import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { AGENT_SPEND_WINDOW_DAYS, agentUsageLogic } from './agentUsageLogic'
import { QuillLoadFailedCallout } from './QuillLoadFailedCallout'

function SpendStat({ label, value }: { label: string; value: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-32 flex-1">
            <Text size="xs" variant="muted" render={<span />}>
                {label}
            </Text>
            <Text size="lg" weight="semibold" render={<span />} translate="no">
                {humanFriendlyCurrency(value)}
            </Text>
        </div>
    )
}

export function QuillAgentUsageSettings(): JSX.Element {
    const { totals, topModels, spendLoading, spendFailed } = useValues(agentUsageLogic)
    const { loadSpend } = useActions(agentUsageLogic)

    if (spendFailed) {
        return (
            <QuillLoadFailedCallout
                message="Your agent spend did not load."
                onRetry={loadSpend}
                loading={spendLoading}
                className="max-w-200"
            />
        )
    }

    if (!totals) {
        return (
            <div className="flex flex-col gap-2 max-w-200">
                <Skeleton className="h-16" />
                <Skeleton className="h-24" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <Card size="sm">
                <CardContent className="flex flex-wrap gap-4">
                    <SpendStat label="Today" value={totals.todayUsd} />
                    <SpendStat label="This month" value={totals.monthUsd} />
                    <SpendStat label={`Last ${AGENT_SPEND_WINDOW_DAYS} days`} value={totals.windowUsd} />
                </CardContent>
            </Card>
            {topModels.length > 0 ? (
                <Table size="sm" fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Model</TableHead>
                            <TableHead align="right">Model calls</TableHead>
                            <TableHead align="right">Spend</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {topModels.map((row) => (
                            <TableRow key={row.model ?? 'other'}>
                                <TableCell expand>
                                    <span translate="no">{row.model ?? 'Other models'}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span translate="no">{row.generation_count.toLocaleString()}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span translate="no">{humanFriendlyCurrency(row.cost_usd)}</span>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            ) : (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {`You have no agent spend in the last ${AGENT_SPEND_WINDOW_DAYS} days.`}
                </Text>
            )}
            <div className="flex">
                <Button
                    variant="outline"
                    render={<LinkPrimitive to={urls.organizationBilling()} />}
                    nativeButton={false}
                >
                    Manage billing
                </Button>
            </div>
        </div>
    )
}
