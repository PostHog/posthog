import './SampleDataState.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useState } from 'react'
import { TextMorph } from 'torph/react'

import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'
import { BarChart, LineChart, PieChart } from '@posthog/quill-charts'
import type { BarChartConfig, LineChartConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { Link } from 'lib/lemon-ui/Link'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { setupWizardStatusLogic } from 'scenes/onboarding/shared/setupWizardStatusLogic'

export type SampleDataVariant = 'line' | 'bar' | 'pie' | 'funnel' | 'number' | 'table'

const WEEK_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const LINE_SERIES: Series[] = [
    { key: 'pageviews', label: 'Pageviews', data: [34, 27, 41, 38, 52, 46, 61], fill: { opacity: 0.1 } },
    { key: 'signups', label: 'Sign-ups', data: [12, 16, 14, 22, 19, 26, 31] },
]
const BAR_SERIES: Series[] = [{ key: 'events', label: 'Events', data: [16, 24, 13, 30, 21, 38, 29] }]
const FUNNEL_LABELS = ['Step 1', 'Step 2', 'Step 3', 'Step 4']
const FUNNEL_SERIES: Series[] = [{ key: 'steps', label: 'Users', data: [412, 265, 179, 112] }]
const PIE_SERIES: Series[] = [
    { key: 'organic', label: 'Organic search', data: [46] },
    { key: 'direct', label: 'Direct', data: [31] },
    { key: 'referral', label: 'Referral', data: [23] },
]
const TABLE_HEADER = ['Event', 'Users', 'Count']
const TABLE_ROWS = [
    ['Pageview', '512', '1,284'],
    ['Sign up', '76', '91'],
    ['Purchase', '24', '30'],
    ['Invite teammate', '12', '16'],
]
// Cycled through by the "number" variant, morphing from one to the next
const SAMPLE_NUMBERS = [1284, 1327, 1291, 1362, 1408, 1373]

const LINE_CONFIG: LineChartConfig = { showGrid: true, showCrosshair: true }
const BAR_CONFIG: BarChartConfig = { bars: { cornerRadius: 2 } }

function SampleNumber({ animate }: { animate: boolean }): JSX.Element {
    const [valueIndex, setValueIndex] = useState(0)

    useEffect(() => {
        if (!animate) {
            return
        }
        const interval = setInterval(() => setValueIndex((index) => (index + 1) % SAMPLE_NUMBERS.length), 4000)
        return () => clearInterval(interval)
    }, [animate])

    return (
        <div className="SampleDataState__number flex flex-col items-center gap-1">
            <TextMorph as="div" className="text-4xl font-semibold tabular-nums text-secondary">
                {humanFriendlyNumber(SAMPLE_NUMBERS[valueIndex])}
            </TextMorph>
            <div className="SampleDataState__row-cell w-16" />
        </div>
    )
}

function SampleTable(): JSX.Element {
    return (
        <div className="w-full max-w-120 self-center m-4 rounded border overflow-hidden text-secondary">
            <div className="flex items-center gap-3 px-3 py-2 bg-surface-secondary text-xs font-semibold">
                {TABLE_HEADER.map((label, cellIndex) => (
                    <div key={cellIndex} className={clsx('flex-1', cellIndex > 0 && 'text-right')}>
                        {label}
                    </div>
                ))}
            </div>
            {TABLE_ROWS.map((cells, index) => (
                <div
                    key={index}
                    className="SampleDataState__row flex items-center gap-3 px-3 py-2 border-t text-sm"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ animationDelay: `${index * 110}ms` }}
                >
                    {cells.map((value, cellIndex) => (
                        <div
                            key={cellIndex}
                            className={clsx(
                                'flex-1',
                                cellIndex === 0 ? 'flex items-center gap-2' : 'text-right tabular-nums'
                            )}
                        >
                            {cellIndex === 0 ? (
                                <>
                                    <div className="SampleDataState__row-cell h-3 w-3 shrink-0 rounded-full" />
                                    <span className="truncate">{value}</span>
                                </>
                            ) : (
                                value
                            )}
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )
}

function SampleChart({ variant }: { variant: Exclude<SampleDataVariant, 'number' | 'table'> }): JSX.Element {
    const theme = useChartTheme()

    return (
        <div className="SampleDataState__chart">
            {variant === 'line' ? (
                <LineChart series={LINE_SERIES} labels={WEEK_LABELS} theme={theme} config={LINE_CONFIG} />
            ) : variant === 'bar' ? (
                <BarChart series={BAR_SERIES} labels={WEEK_LABELS} theme={theme} config={BAR_CONFIG} />
            ) : variant === 'funnel' ? (
                <BarChart series={FUNNEL_SERIES} labels={FUNNEL_LABELS} theme={theme} config={BAR_CONFIG} />
            ) : (
                <PieChart series={PIE_SERIES} theme={theme} />
            )}
        </div>
    )
}

function SampleDataTooltipContent(): JSX.Element {
    const { setupStatus } = useValues(setupWizardStatusLogic)

    return (
        <div className="max-w-72 space-y-1.5 p-0.5">
            <div className="font-semibold">This is sample data</div>
            <p className="m-0">
                This project hasn't received any events yet - you'll see your real data here as soon as events start
                coming in.
            </p>
            {setupStatus?.kind === 'installing' &&
                (setupStatus.mode === 'cloud' ? (
                    <p className="m-0">
                        The setup wizard is installing PostHog in your codebase. Once it's done, it will open a pull
                        request for you to merge.
                    </p>
                ) : (
                    <p className="m-0">
                        The setup wizard is installing PostHog in your codebase. You'll see real data here soon after
                        it's done.
                    </p>
                ))}
            {setupStatus?.kind === 'pull_request' &&
                (setupStatus.pullRequest.merged ? (
                    <p className="m-0">
                        Your setup pull request is merged. Once the updated code is live and sending events, this chart
                        will fill in automatically.
                    </p>
                ) : (
                    <p className="m-0">
                        Your setup pull request hasn't been merged yet -{' '}
                        <Link to={setupStatus.pullRequest.url} target="_blank" targetBlankIcon>
                            merge it
                        </Link>{' '}
                        to start sending events.
                    </p>
                ))}
        </div>
    )
}

/** Obviously-fake placeholder chart shown instead of an empty state before a project has ingested any events. */
export function SampleDataState({ variant = 'line' }: { variant?: SampleDataVariant }): JSX.Element {
    const { setupStatus, setupStatusLoading } = useValues(setupWizardStatusLogic)
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const isStatic =
        inStorybook() ||
        inStorybookTestRunner() ||
        (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

    return (
        <div
            data-attr="insight-sample-data-state"
            className={clsx('SampleDataState', isStatic && 'SampleDataState--static')}
        >
            <div className="SampleDataState__tag flex items-center gap-1">
                {setupStatus?.kind === 'pull_request' && !setupStatus.pullRequest.merged && (
                    <LemonButton size="xsmall" type="primary" to={setupStatus.pullRequest.url} targetBlank>
                        Merge setup PR
                    </LemonButton>
                )}
                {setupStatus?.kind === 'installing' && (
                    <Tooltip
                        title={
                            <div className="max-w-72 space-y-1.5 p-0.5">
                                <div className="font-semibold">Setup wizard is running</div>
                                {setupStatus.mode === 'cloud' ? (
                                    <p className="m-0">
                                        The AI setup wizard is installing PostHog in the cloud, on a copy of your
                                        codebase. Once it's done, it will open a pull request for you to review and
                                        merge.
                                    </p>
                                ) : (
                                    <p className="m-0">
                                        The AI setup wizard is installing PostHog in your codebase from your terminal.
                                        You'll see real data here soon after it's done.
                                    </p>
                                )}
                            </div>
                        }
                        placement="bottom"
                        delayMs={0}
                    >
                        <LemonTag type="muted" className="gap-1 cursor-help">
                            <Spinner className="text-xs" frozen={isStatic} />
                            Installing PostHog...
                        </LemonTag>
                    </Tooltip>
                )}
                {variant === 'line' && !setupStatus && !setupStatusLoading && isCloudOrDev && (
                    <Tooltip
                        title={
                            <div className="max-w-72 space-y-1.5 p-0.5">
                                <div className="font-semibold">AI setup wizard</div>
                                <p className="m-0">
                                    Run this command from the root of your project - the wizard detects your framework,
                                    installs the PostHog SDK, and starts sending events. Click to copy.
                                </p>
                            </div>
                        }
                        placement="bottom"
                        delayMs={0}
                    >
                        <span>
                            <CommandBlock
                                command={wizardCommand}
                                copyLabel="Setup wizard command"
                                ariaLabel="Copy setup wizard command"
                                size="sm"
                                decoration="rainbow"
                                condensed
                                // Sized down to sit flush with the LemonTag next to it
                                className="gap-1 px-1 py-0.5 rounded text-[0.6875rem] leading-4 bg-surface-primary border hover:border-accent"
                            />
                        </span>
                    </Tooltip>
                )}
                <Tooltip title={<SampleDataTooltipContent />} interactive delayMs={100} placement="bottom">
                    <LemonTag className="cursor-help" type="muted">
                        Sample data
                    </LemonTag>
                </Tooltip>
            </div>
            <div className="SampleDataState__viz">
                {variant === 'number' ? (
                    <SampleNumber animate={!isStatic} />
                ) : variant === 'table' ? (
                    <SampleTable />
                ) : (
                    <SampleChart variant={variant} />
                )}
            </div>
        </div>
    )
}
