import {
    Avatar,
    AvatarFallback,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodaySparkline } from 'scenes/project-homepage/today/TodaySparkline'
import { urls } from 'scenes/urls'

import type { BetsEntryApi } from '../generated/api.schemas'
import { BET_STATUS_LABELS } from '../lib/betStatus'
import { money, number } from '../lib/format'

export function BetsTable({ bets }: { bets: BetsEntryApi[] }): JSX.Element {
    return (
        <div className="Bets__table">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>Bet</TableHead>
                        <TableHead>Owner</TableHead>
                        <TableHead>Primary metric</TableHead>
                        <TableHead align="right">Budget</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {bets.map((bet) => (
                        <TableRow key={bet.id} className="Bets__linkedRow relative">
                            <TableCell>
                                <LinkPrimitive className="Bets__betLink" to={urls.bet(bet.id)}>
                                    {bet.title}
                                </LinkPrimitive>
                                <Text size="xs" variant="muted" render={<p className="mt-1 mb-0" />}>
                                    {[BET_STATUS_LABELS[bet.status], bet.area].filter(Boolean).join(' · ')}
                                </Text>
                            </TableCell>
                            <TableCell>
                                <div className="flex items-center gap-2" title={bet.owner.email}>
                                    <Avatar size="xs">
                                        <AvatarFallback>{bet.owner.name.slice(0, 1).toUpperCase()}</AvatarFallback>
                                    </Avatar>
                                    <Text size="sm" className="min-w-0 truncate">
                                        {bet.owner.name}
                                    </Text>
                                </div>
                            </TableCell>
                            <TableCell>
                                <div className="Bets__metricCell">
                                    <div>
                                        <div className="flex flex-wrap items-baseline gap-2">
                                            <span className="tabular-nums">{number(bet.metric.current, bet.unit)}</span>
                                            {bet.target !== null && (
                                                <Text size="xs" variant="muted" className="tabular-nums">
                                                    Target {number(Number(bet.target), bet.unit)}
                                                </Text>
                                            )}
                                        </div>
                                        <Text size="xs" variant="muted" render={<p className="mt-1 mb-0" />}>
                                            {bet.goal_metric || bet.metric.name}
                                        </Text>
                                    </div>
                                    {bet.metric.values.length > 1 && (
                                        <div className="Bets__miniSparkline">
                                            <TodaySparkline
                                                values={bet.metric.values}
                                                labels={bet.metric.dates}
                                                tone="neutral"
                                                emphasizeLast={3}
                                            />
                                        </div>
                                    )}
                                </div>
                            </TableCell>
                            <TableCell align="right">
                                <span className="tabular-nums">
                                    {bet.status === 'closed' ? '—' : money(bet.money.allocated_cents)}
                                </span>
                                <Text
                                    size="xs"
                                    variant="muted"
                                    render={<p className="mt-1 mb-0" />}
                                >{`${money(bet.money.spent_cents)} spent${bet.spend_pending ? ' · settling' : ''}`}</Text>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    )
}
