import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useLayoutEffect, useRef } from 'react'

import { Avatar, AvatarFallback, Badge, Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BetsPage } from '../BetsPage'
import { BetActivity } from '../components/BetActivity'
import { BetConfiguration } from '../components/BetConfiguration'
import { BetDetailSkeleton } from '../components/BetDetailSkeleton'
import { BetGoal } from '../components/BetGoal'
import { BetHeaderStatus } from '../components/BetHeaderStatus'
import { BetIdeas } from '../components/BetIdeas'
import { BetProgress } from '../components/BetProgress'
import { BetResults } from '../components/BetResults'
import { BetsSkeletonLine } from '../components/BetsSkeletonLine'
import { BET_STATUS_BADGES, BET_STATUS_LABELS } from '../lib/betStatus'
import { betLogic } from '../logics/betLogic'

export const scene: SceneExport<{ id: string }> = {
    component: BetDetailScene,
    logic: betLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function BetDetailScene({ id }: { id: string }): JSX.Element {
    const { bet, betLoading, busy, busyOperation, error, breadcrumbs, activity, activityLoading, activityError } =
        useValues(betLogic({ id }))
    const { changeStatus, loadBet, loadActivity, setExpandedWork } = useActions(betLogic({ id }))
    const { searchParams } = useValues(router)
    const live = !!bet && ['setting_up', 'running'].includes(bet.status)
    const workRef = useRef<HTMLDivElement>(null)
    const ideasRef = useRef<HTMLDivElement>(null)
    useLayoutEffect(() => {
        if (bet && searchParams.work) {
            if (bet.work.some((work) => work.id === searchParams.work)) {
                setExpandedWork(searchParams.work)
            }
            workRef.current?.scrollIntoView({ block: 'start' })
        } else if (bet && searchParams.section === 'ideas') {
            ideasRef.current?.scrollIntoView({ block: 'start' })
        }
    }, [bet?.id, searchParams.work, searchParams.section])
    return (
        <BetsPage
            title={
                bet?.title ??
                (error ? (
                    'Bet'
                ) : (
                    <BetsSkeletonLine className="Bets__skeleton pointer-events-none select-none" width="w-80" />
                ))
            }
            titleAddon={bet && <Badge variant={BET_STATUS_BADGES[bet.status]}>{BET_STATUS_LABELS[bet.status]}</Badge>}
            breadcrumbs={breadcrumbs}
            actions={
                bet && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Tooltip>
                            <TooltipTrigger
                                delay={200}
                                render={<Avatar size="sm" className="me-1" data-attr="bets-header-owner" />}
                            >
                                <AvatarFallback>{bet.owner.name.slice(0, 1).toUpperCase()}</AvatarFallback>
                            </TooltipTrigger>
                            <TooltipContent>Owned by {bet.owner.name}</TooltipContent>
                        </Tooltip>
                        {bet.is_owner && (
                            <>
                                {(live || bet.status === 'paused') && (
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        loading={busyOperation === `status:${live ? 'paused' : 'running'}`}
                                        disabled={busy}
                                        onClick={() => changeStatus(live ? 'paused' : 'running')}
                                    >
                                        {live ? 'Pause bet' : 'Resume bet'}
                                    </Button>
                                )}
                                {bet.status !== 'closed' && (
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        render={<LinkPrimitive to={urls.betEdit(id)} />}
                                    >
                                        Edit bet
                                    </Button>
                                )}
                                {bet.status !== 'closed' && (
                                    <Button
                                        size="sm"
                                        variant={['reached', 'spent'].includes(bet.status) ? 'primary' : 'link-muted'}
                                        loading={busyOperation === 'status:closed'}
                                        disabled={busy}
                                        onClick={() => changeStatus('closed')}
                                    >
                                        Close bet
                                    </Button>
                                )}
                            </>
                        )}
                    </div>
                )
            }
        >
            {error && (
                <Text variant="destructive" render={<p role="alert" className="mt-4" />}>
                    {error}
                </Text>
            )}
            {!bet ? (
                error ? (
                    <Button variant="outline" loading={betLoading} onClick={loadBet}>
                        Try again
                    </Button>
                ) : (
                    <BetDetailSkeleton />
                )
            ) : (
                <div className={`Bets__detail${bet.results ? ' Bets__detail--ended' : ''}`}>
                    <div className="Bets__detailIntro">
                        <p className="Bets__thesis mx-0 mt-0 mb-4 max-w-180 text-pretty">{bet.statement}</p>
                        <BetHeaderStatus bet={bet} />
                    </div>
                    <BetConfiguration bet={bet} />
                    {bet.results ? (
                        <div className="Bets__detailMain @container/bets-main min-w-0">
                            <BetResults bet={bet} results={bet.results} />
                        </div>
                    ) : (
                        <div className="Bets__detailMain @container/bets-main min-w-0">
                            <BetGoal bet={bet} />
                            <div ref={ideasRef} className="scroll-mt-6">
                                <BetIdeas bet={bet} />
                            </div>
                            <div ref={workRef} className="scroll-mt-6">
                                <BetProgress bet={bet} />
                            </div>
                        </div>
                    )}
                    <BetActivity
                        entries={activity}
                        loading={activityLoading}
                        error={activityError}
                        onRefresh={loadActivity}
                    />
                </div>
            )}
        </BetsPage>
    )
}
