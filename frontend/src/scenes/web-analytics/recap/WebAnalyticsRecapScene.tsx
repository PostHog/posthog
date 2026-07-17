import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconAtSign, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink, IconSlack } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import type {
    GoalApi,
    RecapHighlightApi,
    TopPageApi,
    TopSourceApi,
    WebAnalyticsRecapResponseApi,
    WoWChangeApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { formatRecapDateRange } from './recapDates'
import { CountUp, Reveal, ScrollHint, TrendPill } from './recapPrimitives'
import { webAnalyticsRecapLogic } from './webAnalyticsRecapLogic'

export const scene: SceneExport = {
    component: WebAnalyticsRecapScene,
    logic: webAnalyticsRecapLogic,
}

function buildRecapMaxPrompt(recap: WebAnalyticsRecapResponseApi): string {
    const change = (c: WoWChangeApi | null): string =>
        c ? ` (${c.direction === 'Up' ? 'up' : 'down'} ${c.percent}%)` : ''
    return (
        `!Here's my website analytics recap for the past week on ${recap.project_name}: ` +
        `${recap.visitors.current.toLocaleString()} visitors${change(recap.visitors.change)}, ` +
        `${recap.pageviews.current.toLocaleString()} pageviews${change(recap.pageviews.change)}, ` +
        `bounce rate ${Math.round(recap.bounce_rate.current)}%${change(recap.bounce_rate.change)}. ` +
        `What are the most important changes, and what should I dig into next?`
    )
}

function Section({
    children,
    className,
    overlay,
}: {
    children: React.ReactNode
    className?: string
    overlay?: React.ReactNode
}): JSX.Element {
    return (
        <section
            className={clsx(
                'snap-start shrink-0 min-h-[72%] w-full flex flex-col items-center justify-center px-4 py-[8vh]',
                className
            )}
        >
            <div className="w-full max-w-3xl my-auto">{children}</div>
            {overlay}
        </section>
    )
}

function WhitePanel({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return (
        <div
            className={clsx(
                'rounded-3xl bg-surface-primary shadow-xl p-8 md:p-10 min-h-[56vh] flex flex-col justify-center',
                className
            )}
        >
            {children}
        </div>
    )
}

function MetricTile({
    label,
    value,
    change,
}: {
    label: string
    value: React.ReactNode
    change: WoWChangeApi | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 rounded-xl bg-surface-secondary p-4">
            <span className="text-sm text-secondary">{label}</span>
            <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold font-title tracking-tight tabular-nums">{value}</span>
                <TrendPill change={change} />
            </div>
        </div>
    )
}

function LeaderboardRow({
    rank,
    label,
    value,
    pct,
    change,
}: {
    rank: number
    label: string
    value: string
    pct: number
    change: WoWChangeApi | null
}): JSX.Element {
    return (
        <div className="relative flex items-center justify-between gap-3 overflow-hidden rounded-lg px-3 py-2.5">
            <div
                aria-hidden
                className="absolute inset-y-0 left-0 rounded-lg"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: `${Math.max(pct, 3)}%`,
                    background: 'color-mix(in oklab, var(--recap-accent) 14%, transparent)',
                }}
            />
            <span className="relative flex min-w-0 items-center gap-3">
                <span
                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ background: 'color-mix(in oklab, var(--recap-accent) 24%, transparent)' }}
                >
                    {rank}
                </span>
                <span className="truncate font-medium">{label}</span>
            </span>
            <span className="relative flex shrink-0 items-center gap-3">
                <span className="font-title font-semibold tabular-nums">{value}</span>
                <TrendPill change={change} />
            </span>
        </div>
    )
}

export function WebAnalyticsRecapScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { recap: loadedRecap, recapLoading } = useValues(webAnalyticsRecapLogic)
    const recap = loadedRecap as WebAnalyticsRecapResponseApi | null
    const {
        recordReachedEnd,
        recordCtaClicked,
        copyRecapLink,
        copyRecapForSlack,
        copyRecapForEmail,
        goToWebAnalytics,
    } = useActions(webAnalyticsRecapLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 60, power: 6, duration: 2500 })

    const endRef = useRef<HTMLDivElement>(null)
    const celebratedRef = useRef(false)
    const reachedEndRef = useRef(false)
    const [scrolledPastIntro, setScrolledPastIntro] = useState(false)

    // One celebratory burst once the recap has loaded.
    useEffect(() => {
        if (recap && !celebratedRef.current) {
            celebratedRef.current = true
            triggerHogfetti()
        }
    }, [recap, triggerHogfetti])

    useEffect(() => {
        const node = endRef.current
        if (!node || typeof IntersectionObserver === 'undefined') {
            return
        }
        const observer = new IntersectionObserver(([entry]) => {
            if (entry.isIntersecting && !reachedEndRef.current) {
                reachedEndRef.current = true
                recordReachedEnd()
                observer.disconnect()
            }
        })
        observer.observe(node)
        return () => observer.disconnect()
    }, [recap, recordReachedEnd])

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_RECAP]) {
        return <NotFound object="page" />
    }

    if (recapLoading && !recap) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-3">
                <Spinner className="text-3xl" />
                <span className="text-secondary">Wrapping up your week…</span>
            </div>
        )
    }

    if (!recap) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-4">
                <span className="text-2xl">🦔</span>
                <h2>Your recap isn't ready yet</h2>
                <p className="text-secondary max-w-md">
                    We couldn't build a recap for this project right now. Once there's some traffic, check back here.
                </p>
                <LemonButton type="primary" onClick={() => goToWebAnalytics('go_to_web_analytics')}>
                    Go to web analytics
                </LemonButton>
            </div>
        )
    }

    const persona = recap.persona
    const maxPageVisitors = Math.max(...recap.top_pages.map((page) => page.visitors), 1)
    const maxSourceVisitors = Math.max(...recap.top_sources.map((source) => source.visitors), 1)
    const maxGoalConversions = Math.max(...recap.goals.map((goal) => goal.conversions), 1)

    return (
        <div
            className="WebAnalyticsRecap relative isolate h-full overflow-y-auto overflow-x-hidden overscroll-contain snap-y snap-mandatory"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--recap-accent': persona.color } as React.CSSProperties}
        >
            <HogfettiComponent />

            {/* Cohesive full-bleed backdrop pinned behind the snapping sections */}
            <div aria-hidden className="sticky top-0 z-0 h-0">
                <div
                    className="absolute top-0 left-0 right-0 h-screen -z-10"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        background:
                            'radial-gradient(1200px 600px at 50% -10%, color-mix(in oklab, var(--recap-accent) 18%, transparent), transparent 60%), linear-gradient(180deg, var(--color-bg-surface-secondary), var(--color-bg-primary))',
                    }}
                />
            </div>

            <div className="contents">
                <Section
                    className="text-center text-white relative"
                    overlay={
                        <ScrollHint
                            className={clsx(
                                'absolute bottom-[6vh] left-1/2 -translate-x-1/2 transition-opacity duration-500',
                                scrolledPastIntro && 'opacity-0'
                            )}
                        />
                    }
                >
                    <Reveal>
                        <div
                            className="rounded-2xl px-6 py-16 md:py-20 shadow-xl min-h-[56vh] flex flex-col justify-center"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: 'linear-gradient(135deg, #1d1f27 0%, #2b2333 100%)' }}
                        >
                            <p className="text-sm uppercase tracking-widest opacity-70">
                                {formatRecapDateRange(recap)}
                            </p>
                            <h1 className="font-title text-5xl md:text-6xl font-extrabold tracking-tight mt-3 text-white">
                                {recap.project_name}'s week on the web
                            </h1>
                        </div>
                    </Reveal>
                </Section>

                {/* 2. Headline number */}
                <Section className="text-center">
                    <Reveal onInView={() => setScrolledPastIntro(true)}>
                        <WhitePanel className="text-center">
                            <p className="text-sm uppercase tracking-widest text-secondary">
                                This week your website welcomed
                            </p>
                            <div className="flex flex-1 flex-col items-center justify-center">
                                <div className="flex items-end justify-center gap-3">
                                    <CountUp
                                        value={recap.visitors.current}
                                        className="font-title text-7xl md:text-8xl font-bold leading-none tracking-tight text-[color:var(--recap-accent)]"
                                    />
                                    <TrendPill change={recap.visitors.change} className="text-xl mb-2" />
                                </div>
                                <p className="text-2xl text-secondary mt-3">visitors</p>
                            </div>
                        </WhitePanel>
                    </Reveal>
                </Section>

                {/* 3. Persona */}
                <Section className="text-center">
                    <Reveal>
                        <div
                            className="rounded-2xl p-10 text-white shadow-xl min-h-[56vh] flex flex-col justify-center"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ background: persona.color }}
                        >
                            <div className="text-6xl">{persona.emoji}</div>
                            <p className="uppercase tracking-widest opacity-80 mt-4 text-sm">Your persona</p>
                            <h2 className="font-title text-4xl font-extrabold mt-1 text-white">{persona.name}</h2>
                            <p className="text-lg opacity-90 mt-3 max-w-xl mx-auto">{persona.blurb}</p>
                        </div>
                    </Reveal>
                </Section>

                {/* 4. Vital signs */}
                <Section>
                    <Reveal>
                        <WhitePanel>
                            <h3 className="font-title text-2xl font-bold mb-4 text-center">Your week in numbers</h3>
                            <div className="grid grid-cols-2 gap-3 flex-1 content-center">
                                <MetricTile
                                    label="Pageviews"
                                    value={<CountUp value={recap.pageviews.current} />}
                                    change={recap.pageviews.change}
                                />
                                <MetricTile
                                    label="Sessions"
                                    value={<CountUp value={recap.sessions.current} />}
                                    change={recap.sessions.change}
                                />
                                <MetricTile
                                    label="Bounce rate"
                                    value={`${Math.round(recap.bounce_rate.current)}%`}
                                    change={recap.bounce_rate.change}
                                />
                                <MetricTile
                                    label="Avg. session"
                                    value={recap.avg_session_duration.current}
                                    change={recap.avg_session_duration.change}
                                />
                            </div>
                        </WhitePanel>
                    </Reveal>
                </Section>

                {/* 5. Top pages */}
                {recap.top_pages.length > 0 && (
                    <Section>
                        <Reveal>
                            <WhitePanel>
                                <h3 className="font-title text-2xl font-bold mb-4 text-center">Your top pages</h3>
                                <div className="flex flex-1 flex-col justify-center gap-1.5">
                                    {recap.top_pages.map((page: TopPageApi, index: number) => (
                                        <LeaderboardRow
                                            key={`${page.host}::${page.path}`}
                                            rank={index + 1}
                                            label={page.path || '/'}
                                            value={page.visitors.toLocaleString()}
                                            pct={(page.visitors / maxPageVisitors) * 100}
                                            change={page.change}
                                        />
                                    ))}
                                </div>
                            </WhitePanel>
                        </Reveal>
                    </Section>
                )}

                {/* 6. Top sources */}
                {recap.top_sources.length > 0 && (
                    <Section>
                        <Reveal>
                            <WhitePanel>
                                <h3 className="font-title text-2xl font-bold mb-4 text-center">Where they came from</h3>
                                <div className="flex flex-1 flex-col justify-center gap-1.5">
                                    {recap.top_sources.map((source: TopSourceApi, index: number) => (
                                        <LeaderboardRow
                                            key={`${source.name}-${index}`}
                                            rank={index + 1}
                                            label={source.name}
                                            value={source.visitors.toLocaleString()}
                                            pct={(source.visitors / maxSourceVisitors) * 100}
                                            change={source.change}
                                        />
                                    ))}
                                </div>
                            </WhitePanel>
                        </Reveal>
                    </Section>
                )}

                {/* 7. Goals */}
                {recap.goals.length > 0 && (
                    <Section>
                        <Reveal>
                            <WhitePanel>
                                <h3 className="font-title text-2xl font-bold mb-4 text-center">Goals you hit</h3>
                                <div className="flex flex-1 flex-col justify-center gap-1.5">
                                    {recap.goals.map((goal: GoalApi, index: number) => (
                                        <LeaderboardRow
                                            key={`${goal.name}-${index}`}
                                            rank={index + 1}
                                            label={goal.name}
                                            value={goal.conversions.toLocaleString()}
                                            pct={(goal.conversions / maxGoalConversions) * 100}
                                            change={goal.change}
                                        />
                                    ))}
                                </div>
                            </WhitePanel>
                        </Reveal>
                    </Section>
                )}

                {/* 8. Highlights / badges */}
                {recap.highlights.length > 0 && (
                    <Section>
                        <Reveal>
                            <WhitePanel>
                                <h3 className="font-title text-2xl font-bold mb-4 text-center">This week's wins</h3>
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 flex-1 content-center">
                                    {recap.highlights.map((highlight: RecapHighlightApi) => (
                                        <div
                                            key={highlight.id}
                                            className="flex flex-col gap-1 rounded-xl bg-surface-secondary p-4 text-center"
                                        >
                                            <span className="text-3xl">{highlight.emoji}</span>
                                            <span className="text-sm text-secondary">{highlight.title}</span>
                                            <span className="text-lg font-bold truncate">{highlight.value}</span>
                                            <span className="text-xs text-muted">{highlight.detail}</span>
                                        </div>
                                    ))}
                                </div>
                            </WhitePanel>
                        </Reveal>
                    </Section>
                )}

                {/* 9. Max's take */}
                <Section className="text-center">
                    <Reveal>
                        <div className="rounded-3xl bg-surface-primary shadow-xl p-10 min-h-[56vh] flex flex-col items-center justify-center">
                            <IconSparkles className="text-4xl text-accent mx-auto" />
                            <h3 className="font-title text-2xl font-bold mt-3">Curious what's behind the numbers?</h3>
                            <p className="text-secondary mt-2">
                                PostHog AI can explain what changed this week and what to look at next.
                            </p>
                            <LemonButton
                                type="primary"
                                className="mt-5 mx-auto"
                                icon={<IconSparkles />}
                                onClick={() => {
                                    recordCtaClicked('ask_posthog_ai')
                                    openSidePanel(SidePanelTab.Max, buildRecapMaxPrompt(recap))
                                }}
                            >
                                Ask PostHog AI about your week
                            </LemonButton>
                        </div>
                    </Reveal>
                </Section>

                {/* 10. Outro & share */}
                <Section className="text-center">
                    <Reveal>
                        <WhitePanel>
                            <h2 className="font-title text-3xl font-extrabold">See you next week 👋</h2>
                            <p className="text-secondary mt-2">Share your week or dive into the details.</p>
                            <div className="flex flex-wrap items-center justify-center gap-2 mt-6">
                                <LemonButton type="secondary" icon={<IconLink />} onClick={copyRecapLink}>
                                    Copy link
                                </LemonButton>
                                <LemonButton type="secondary" icon={<IconSlack />} onClick={copyRecapForSlack}>
                                    Copy for Slack
                                </LemonButton>
                                <LemonButton type="secondary" icon={<IconAtSign />} onClick={copyRecapForEmail}>
                                    Copy for email
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    sideIcon={<IconArrowRight />}
                                    onClick={() => {
                                        goToWebAnalytics('view_dashboard')
                                    }}
                                >
                                    Explore full dashboard
                                </LemonButton>
                            </div>
                        </WhitePanel>
                    </Reveal>
                </Section>

                <div ref={endRef} aria-hidden className="h-[30vh]" />
            </div>
        </div>
    )
}
