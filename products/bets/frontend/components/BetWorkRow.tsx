import { useActions, useValues } from 'kea'

import { IconCode, IconFlask, IconToggle } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { urls } from 'scenes/urls'

import { getIconColor } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { BetsDetailApi, BetsWorkApi } from '../generated/api.schemas'
import { number } from '../lib/format'
import { planSummary } from '../lib/plan'
import { isOpen, liveFact, workStatus } from '../lib/workStatus'
import { betLogic } from '../logics/betLogic'
import { BetPlanDecision } from './BetPlanDecision'
import { BetResourceLink } from './BetResourceLink'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

function effect(item: BetsWorkApi): string {
    const variant = item.result.variant && item.result.variant !== 'control' ? item.result.variant : 'test'
    const bounds = item.result.primary?.[variant]
    if (!bounds || bounds.length !== 2) {
        return ''
    }
    return `Effect on the primary metric: ${number(bounds[0] * 100, '%')} to ${number(bounds[1] * 100, '%')}`
}

export function BetWorkRow({ item, bet }: { item: BetsWorkApi; bet: BetsDetailApi }): JSX.Element {
    const { busy, busyOperation, openWork, pullRequestTitles } = useValues(betLogic({ id: bet.id }))
    const { setExpandedWork, work, openTask } = useActions(betLogic({ id: bet.id }))
    const status = workStatus(item)
    const idea = item.kind === 'idea'
    const cleanup = item.kind === 'cleanup'
    const [iconColor] = getIconColor(idea ? 'experiment' : 'task')
    const exposures = Object.values(item.result.exposures ?? {}).reduce((total, value) => total + value, 0)
    const pullRequestTitle = (item.task_id && pullRequestTitles[item.task_id]) || 'Pull request'
    const live = item.stage === 'live'
    const needsDecision = live && idea && !!item.plan.proposed_days
    const summary = idea && isOpen(item) ? planSummary(item.plan) : ''
    const facts = [
        status.label,
        needsDecision ? 'Needs more days' : live && item.note ? liveFact(item.note) : '',
        item.stage === 'live' && exposures ? `${number(exposures)} people exposed` : '',
    ]
    const expanded = openWork === item.id
    return (
        <TodayRow
            tone={item.stage === 'stuck' ? 'risk' : isOpen(item) ? 'neutral' : 'quiet'}
            icon={{
                color: cleanup ? undefined : iconColor,
                glyph: idea ? <IconFlask /> : cleanup ? <IconToggle /> : <IconCode />,
            }}
            title={item.title}
            facts={facts.filter(Boolean)}
            statusIcon={<BetWorkStatusIcon status={status} />}
            actions={
                bet.is_owner && item.stage === 'stuck' ? (
                    <Button
                        size="sm"
                        variant="outline"
                        loading={busyOperation === `work:${item.id}:retry`}
                        disabled={busy}
                        onClick={() => work({ work_id: item.id, action: 'retry' })}
                        data-attr="bets-work-retry"
                    >
                        Retry
                    </Button>
                ) : bet.is_owner && needsDecision && openWork !== item.id ? (
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setExpandedWork(item.id)}
                        data-attr="bets-work-decide"
                    >
                        Extend or stop
                    </Button>
                ) : item.stage === 'review' && item.pr_url ? (
                    <Button
                        size="sm"
                        variant="outline"
                        render={<LinkPrimitive to={item.pr_url} target="_blank" />}
                        data-attr="bets-work-review-pr"
                    >
                        Review pull request
                    </Button>
                ) : undefined
            }
            expansion={{
                expanded,
                onToggle: () => setExpandedWork(expanded ? null : item.id),
                detail: (
                    <div className="TodayRow__detailBody min-w-0 pb-2">
                        <div className="max-w-prose flex flex-col gap-3">
                            {item.note && (
                                <Text
                                    size="sm"
                                    variant={
                                        item.stage === 'stuck' ? 'destructive' : needsDecision ? 'default' : 'muted'
                                    }
                                >
                                    {item.note}
                                </Text>
                            )}
                            {summary && (
                                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                    {summary}
                                </Text>
                            )}
                            <BetPlanDecision item={item} bet={bet} />
                            {item.result.summary && (
                                <Text size="sm" render={<p className="m-0 leading-relaxed" />}>
                                    {item.result.summary}
                                </Text>
                            )}
                            {effect(item) && (
                                <Text size="sm" variant="muted">
                                    {effect(item)}
                                </Text>
                            )}
                            {item.summary && (
                                <LemonMarkdown
                                    className="Bets__taskFindings"
                                    lowKeyHeadings
                                    disableImages="all"
                                    disableMentions
                                >
                                    {item.summary}
                                </LemonMarkdown>
                            )}
                        </div>
                        <div className="Bets__taskResources flex flex-wrap gap-2">
                            {item.pr_url && (
                                <BetResourceLink
                                    kind="pull_request"
                                    title={pullRequestTitle}
                                    detail={item.pr_state || undefined}
                                    href={item.pr_url}
                                />
                            )}
                            {item.experiment_id && (
                                <BetResourceLink
                                    kind="experiment"
                                    title="Experiment"
                                    detail={item.flag_key}
                                    href={urls.experiment(item.experiment_id)}
                                    id={String(item.experiment_id)}
                                />
                            )}
                        </div>
                        <div className="TodayRow__detailFooter gap-3">
                            {bet.is_owner && idea && isOpen(item) && !needsDecision && (
                                <Button
                                    size="sm"
                                    variant="link-muted"
                                    loading={busyOperation === `work:${item.id}:drop`}
                                    disabled={busy}
                                    onClick={() => work({ work_id: item.id, action: 'drop' })}
                                    data-attr="bets-work-drop"
                                >
                                    Drop idea
                                </Button>
                            )}
                            {item.task_id && (
                                <Button
                                    size="sm"
                                    variant="outline"
                                    className="ml-auto"
                                    loading={busyOperation === `open-task:${item.task_id}`}
                                    disabled={busy}
                                    onClick={() => openTask(item.task_id!)}
                                    data-attr="bets-work-open-task"
                                >
                                    {['queued', 'in_progress'].includes(item.task_status)
                                        ? 'View live task'
                                        : 'Open task'}
                                </Button>
                            )}
                        </div>
                    </div>
                ),
            }}
            dataAttr="bets-work"
        />
    )
}
