import { useActions, useValues } from 'kea'

import { Badge, Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { BetsDetailApi } from '../generated/api.schemas'
import { BET_STATUS_LABELS } from '../lib/betStatus'
import { ideasCount, waitingIdeas } from '../lib/ideas'
import { isOpen } from '../lib/workStatus'
import { betLogic } from '../logics/betLogic'

const STATUS_BADGE: Record<BetsDetailApi['status'], 'default' | 'success' | 'warning' | 'completed' | 'destructive'> = {
    setting_up: 'default',
    running: 'success',
    paused: 'warning',
    reached: 'completed',
    spent: 'warning',
    closed: 'default',
}

export function BetHeaderStatus({ bet }: { bet: BetsDetailApi }): JSX.Element {
    const { setExpandedWork } = useActions(betLogic({ id: bet.id }))
    const { goalConfirmAt } = useValues(betLogic({ id: bet.id }))
    const live = ['setting_up', 'running'].includes(bet.status)
    const current = bet.work.find((item) => item.goal_version === bet.goal_version && isOpen(item))
    const testing = live && current?.kind === 'idea' ? current : null
    const step = !live
        ? ''
        : current?.kind === 'tracking'
          ? 'Checking how the goal is measured'
          : bet.scout?.running
            ? 'Finding the next idea'
            : ''
    const goalMet = bet.status === 'running' && !current && !!bet.goal_met_since
    const waiting = live && !current && !goalMet ? waitingIdeas(bet).length : 0
    const note = live && !waiting && !(goalMet && goalConfirmAt) ? bet.note.replace(/\.$/, '') : ''
    return (
        <div className="Bets__status grid min-w-0 items-center gap-x-2.5 gap-y-1" data-attr="bets-coordination-status">
            <Badge variant={STATUS_BADGE[bet.status]}>{BET_STATUS_LABELS[bet.status]}</Badge>
            {testing ? (
                <Text size="sm" render={<span />} className="flex min-w-0 items-baseline gap-1 whitespace-nowrap">
                    <span className="shrink-0">Testing</span>
                    <Tooltip>
                        <TooltipTrigger
                            delay={400}
                            render={
                                <Button
                                    size="inline"
                                    variant="link-muted"
                                    className="Bets__statusIdea max-w-full min-w-0 shrink overflow-hidden font-medium"
                                    onClick={() => setExpandedWork(testing.id)}
                                    data-attr="bets-header-current-idea"
                                />
                            }
                        >
                            <span className="truncate">{testing.title}</span>
                        </TooltipTrigger>
                        <TooltipContent>{testing.title}</TooltipContent>
                    </Tooltip>
                </Text>
            ) : goalMet ? (
                <Text size="sm" render={<span />} className="flex min-w-0 items-baseline gap-1 whitespace-nowrap">
                    <span className="shrink-0">The goal is at the target</span>
                    {goalConfirmAt && (
                        <Text size="sm" variant="muted" render={<span className="ms-1 flex gap-1" />}>
                            <span>Bets confirms it</span>
                            <TZLabel time={goalConfirmAt} />
                        </Text>
                    )}
                </Text>
            ) : waiting ? (
                <Text size="sm" render={<span />} className="flex min-w-0 items-baseline gap-1 whitespace-nowrap">
                    <Button
                        size="inline"
                        variant="link-muted"
                        className="Bets__statusIdea max-w-full min-w-0 font-medium"
                        onClick={() => document.getElementById('bet-ideas')?.scrollIntoView({ behavior: 'smooth' })}
                        data-attr="bets-header-choose-idea"
                    >
                        Choose an idea to build
                    </Button>
                    <Text size="sm" variant="muted" render={<span />} className="ms-1">
                        {ideasCount(waiting)}
                    </Text>
                </Text>
            ) : (
                step && (
                    <Text size="sm" render={<span />} className="flex min-w-0 items-baseline gap-1 whitespace-nowrap">
                        {step}
                    </Text>
                )
            )}
            {note && (
                <Text size="sm" variant="muted" render={<p />} className="col-start-2 m-0">
                    {note}
                </Text>
            )}
        </div>
    )
}
