import { useValues } from 'kea'

import { Table, TableBody, TableCell, TableRow, Text } from '@posthog/quill'

import { DEFAULT_PAID_RESPONSE_TIME, getSupportPlanRows } from 'lib/components/Support/supportResponseTime'
import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

export function TodaySupportResponseTimes(): JSX.Element {
    const { billing, billingPlan, supportPlans } = useValues(billingLogic)
    const { user } = useValues(userLogic)

    const rows = getSupportPlanRows({ billing, billingPlan, supportPlans, organizationId: user?.organization?.id })
    const trial = billing?.trial
    const activeTrial = trial?.status === 'active' && ['boost', 'scale', 'enterprise'].includes(trial.target ?? '')

    return (
        <div className="flex flex-col gap-1">
            <Table size="sm" fullWidth className="rounded-md border border-border">
                <TableBody>
                    {rows.map((row) => (
                        <TableRow key={row.key}>
                            <TableCell className={row.isCurrentPlan ? 'font-semibold' : undefined}>
                                <span data-attr="support-plan-name">
                                    {row.name}
                                    {row.legacy && <span className="font-normal text-muted-foreground"> (legacy)</span>}
                                    {row.isCurrentPlan && (
                                        <span className="font-normal text-muted-foreground"> (your plan)</span>
                                    )}
                                </span>
                            </TableCell>
                            <TableCell align="right" className={row.isCurrentPlan ? 'font-semibold' : undefined}>
                                <span data-attr="support-response-time">
                                    {!row.responseTime && row.link ? (
                                        // eslint-disable-next-line react/forbid-elements
                                        <a
                                            href={row.link}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="underline"
                                        >
                                            Community forum
                                        </a>
                                    ) : (
                                        row.responseTime || 'Community support only'
                                    )}
                                </span>
                            </TableCell>
                        </TableRow>
                    ))}
                    {activeTrial && (
                        <TableRow>
                            <TableCell className="font-semibold">Your trial</TableCell>
                            <TableCell align="right" className="font-semibold">
                                {DEFAULT_PAID_RESPONSE_TIME}
                            </TableCell>
                        </TableRow>
                    )}
                </TableBody>
            </Table>
            {activeTrial && trial?.expires_at && (
                <Text size="xs" variant="muted">
                    Trial expires {dayjs(trial.expires_at).format('MMMM D, YYYY')}
                </Text>
            )}
            {!activeTrial && trial?.status === 'expired' && (
                <Text size="xs" variant="muted">
                    Trial expired
                </Text>
            )}
        </div>
    )
}
