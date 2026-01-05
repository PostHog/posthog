import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyDuration } from 'lib/utils'

import { EXPERIMENT_REFRESH_INTERVAL_SECONDS } from '../constants'
import { experimentLogic } from '../experimentLogic'

export const ExperimentLastRefreshText = (): JSX.Element => {
    const { effectiveLastRefresh } = useValues(experimentLogic)
    return (
        <div className="flex items-center gap-1">
            {effectiveLastRefresh && dayjs().diff(dayjs(effectiveLastRefresh), 'hour') < 24 ? (
                <div className="flex items-center gap-1">
                    <span>Last refreshed</span>
                    <TZLabel time={effectiveLastRefresh} />
                </div>
            ) : (
                'Refresh'
            )}
        </div>
    )
}

const INTERVAL_OPTIONS = Array.from(EXPERIMENT_REFRESH_INTERVAL_SECONDS, (value) => ({
    label: humanFriendlyDuration(value),
    value: value,
}))

export function ExperimentReloadAction(): JSX.Element {
    const {
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
        autoRefresh,
        blockRefresh,
        nextAllowedExperimentRefresh,
    } = useValues(experimentLogic)
    const { refreshExperimentResults, setAutoRefresh, setPageVisibility } = useActions(experimentLogic)

    const isRefreshing = primaryMetricsResultsLoading || secondaryMetricsResultsLoading

    usePageVisibilityCb((pageIsVisible) => {
        setPageVisibility(pageIsVisible)
    })

    // Force re-render when cooldown expires
    const [, setRenderTrigger] = useState(0)
    useEffect(() => {
        if (nextAllowedExperimentRefresh) {
            const msUntilRefreshAllowed = dayjs(nextAllowedExperimentRefresh).diff(dayjs())
            if (msUntilRefreshAllowed > 0) {
                const timeoutId = setTimeout(() => setRenderTrigger((n) => n + 1), msUntilRefreshAllowed + 100)
                return () => clearTimeout(timeoutId)
            }
        }
    }, [nextAllowedExperimentRefresh])

    const options = INTERVAL_OPTIONS.map((option) => ({
        ...option,
        disabledReason: !autoRefresh.enabled ? 'Enable auto refresh to set the interval' : undefined,
    }))

    return (
        <div className="relative">
            <LemonButton
                onClick={() => refreshExperimentResults(true)}
                type="secondary"
                size="xsmall"
                icon={
                    isRefreshing ? (
                        <Spinner textColored />
                    ) : blockRefresh &&
                      nextAllowedExperimentRefresh &&
                      dayjs(nextAllowedExperimentRefresh).isAfter(dayjs()) ? (
                        <IconCheck />
                    ) : (
                        <IconRefresh />
                    )
                }
                data-attr="refresh-experiment"
                tooltip="Refresh experiment results"
                disabledReason={
                    blockRefresh &&
                    nextAllowedExperimentRefresh &&
                    dayjs(nextAllowedExperimentRefresh).isAfter(dayjs())
                        ? `Next refresh possible ${dayjs(nextAllowedExperimentRefresh).fromNow()}`
                        : isRefreshing
                          ? 'Loading...'
                          : ''
                }
                sideAction={{
                    'data-attr': 'refresh-experiment-dropdown',
                    dropdown: {
                        closeOnClickInside: false,
                        placement: 'bottom-end',
                        overlay: (
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: () => (
                                            <LemonSwitch
                                                onChange={(checked) => setAutoRefresh(checked, autoRefresh.interval)}
                                                label="Auto refresh while on page"
                                                checked={autoRefresh.enabled}
                                                fullWidth
                                                className="mt-1 mb-2"
                                            />
                                        ),
                                    },
                                    {
                                        title: 'Refresh interval',
                                        items: [
                                            {
                                                label: () => (
                                                    <LemonRadio
                                                        value={autoRefresh.interval}
                                                        options={options}
                                                        onChange={(value: number) => {
                                                            setAutoRefresh(true, value)
                                                        }}
                                                        className="mx-2 mb-1"
                                                    />
                                                ),
                                            },
                                        ],
                                    },
                                ]}
                            />
                        ),
                    },
                }}
            >
                <span className={clsx('refresh-experiment-text')}>
                    {isRefreshing ? 'Loading...' : <ExperimentLastRefreshText />}
                </span>
            </LemonButton>
            <LemonBadge
                size="small"
                content={
                    <>
                        <IconRefresh className="mr-0" /> {humanFriendlyDuration(autoRefresh.interval)}
                    </>
                }
                visible={autoRefresh.enabled}
                position="top-right"
                status="muted"
            />
        </div>
    )
}
