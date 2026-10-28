import { useActions, useValues } from 'kea'

import {
    IconArchive,
    IconCheck,
    IconCode,
    IconFlask,
    IconLightBulb,
    IconPause,
    IconPullRequest,
    IconTelescope,
    IconWarning,
} from '@posthog/icons'
import { Button, IconStack, IconStackItem, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { getIconColor } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import type { BetsDetailApi, BetsStateActionApi, BetTileEnumApi } from '../generated/api.schemas'
import { IDEA_ICON_COLOR } from '../lib/ideas'
import { betLogic } from '../logics/betLogic'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

const MUTED = 'var(--muted-foreground)'

const TILES: Record<Exclude<BetTileEnumApi, 'measure'>, { color: string; glyph: JSX.Element }> = {
    tracking: { color: getIconColor('task')[0], glyph: <IconCode /> },
    scout: { color: 'var(--color-product-self-driving-light)', glyph: <IconTelescope /> },
    idea: { color: IDEA_ICON_COLOR, glyph: <IconLightBulb /> },
    experiment: { color: getIconColor('experiment')[0], glyph: <IconFlask /> },
    pull_request: { color: getIconColor('task')[0], glyph: <IconPullRequest /> },
    problem: { color: 'var(--warning-foreground)', glyph: <IconWarning /> },
    idle: { color: MUTED, glyph: <IconLightBulb /> },
    paused: { color: MUTED, glyph: <IconPause /> },
    reached: { color: 'var(--completed-foreground)', glyph: <IconCheck /> },
    ended: { color: MUTED, glyph: <IconArchive /> },
}

const ACTION_ATTRS: Partial<Record<BetsStateActionApi['kind'], string>> = {
    edit: 'bets-header-set-target',
    ideas: 'bets-header-choose-idea',
}

function StatusTile({ tile }: { tile: BetTileEnumApi }): JSX.Element {
    if (tile === 'measure') {
        return <TodayObjectIcon type="insight" className="[--icon-stack-size:32px] shrink-0" />
    }
    return (
        <IconStack className="[--icon-stack-size:32px] shrink-0">
            <IconStackItem color={TILES[tile].color}>{TILES[tile].glyph}</IconStackItem>
        </IconStack>
    )
}

function StatusAction({ bet, action }: { bet: BetsDetailApi; action: BetsStateActionApi }): JSX.Element {
    const { runStateAction } = useActions(betLogic({ id: bet.id }))
    const { busy, busyOperation } = useValues(betLogic({ id: bet.id }))
    const link =
        action.kind === 'pull_request' ? (
            <LinkPrimitive to={action.url} target="_blank" />
        ) : action.kind === 'settings' ? (
            <LinkPrimitive to={urls.betsSettings()} />
        ) : ['edit', 'budget'].includes(action.kind) ? (
            <LinkPrimitive to={urls.betEdit(bet.id)} />
        ) : undefined
    return (
        <Button
            variant={action.primary ? 'primary' : 'outline'}
            size="sm"
            disabled={!link && busy}
            loading={busyOperation === `work:${action.work_id}:${action.work_action}`}
            render={link}
            onClick={link ? undefined : () => runStateAction(action)}
            data-attr={ACTION_ATTRS[action.kind] ?? `bets-header-${action.kind}`}
        >
            {action.label}
        </Button>
    )
}

export function BetHeaderStatus({ bet }: { bet: BetsDetailApi }): JSX.Element {
    const { setExpandedWork } = useActions(betLogic({ id: bet.id }))
    const { state } = bet
    const actions = bet.is_owner ? [state.action, state.alternative].filter((item) => item !== null) : []
    return (
        <div className="mb-1 flex min-w-0 items-center gap-3" data-attr="bets-coordination-status">
            <StatusTile tile={state.tile} />
            <div className="flex max-w-180 min-w-0 flex-1 flex-col gap-0.5">
                <Text size="sm" weight="medium" render={<p className="m-0" />}>
                    {state.headline}
                </Text>
                <Text
                    size="xs"
                    variant="muted"
                    render={<p className="m-0" />}
                    className="flex min-w-0 flex-wrap items-center gap-x-1.5"
                >
                    {state.working && <BetWorkStatusIcon status={{ label: 'Working', mark: 'spinner' }} />}
                    {state.subject && state.work_id && (
                        <span className="flex max-w-max min-w-0 flex-[1_1_15rem] items-center gap-1.5">
                            <Tooltip>
                                <TooltipTrigger
                                    delay={400}
                                    render={
                                        <Button
                                            size="inline"
                                            variant="link-muted"
                                            className="min-w-0 shrink overflow-hidden"
                                            onClick={() => setExpandedWork(state.work_id)}
                                            data-attr="bets-header-current-idea"
                                        />
                                    }
                                >
                                    <span className="truncate">{state.subject}</span>
                                </TooltipTrigger>
                                <TooltipContent>{state.subject}</TooltipContent>
                            </Tooltip>
                            {state.detail && <span className="shrink-0">·</span>}
                        </span>
                    )}
                    {state.detail && <span className="min-w-0">{state.detail}</span>}
                </Text>
            </div>
            {actions.length > 0 && (
                <div className="ms-auto flex shrink-0 items-center gap-2">
                    {actions.map((action) => (
                        <StatusAction key={action.label} bet={bet} action={action} />
                    ))}
                </div>
            )}
        </div>
    )
}
