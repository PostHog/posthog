import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Label } from 'lib/ui/Label/Label'
import { humanFriendlyDuration } from 'lib/utils'

import { experimentLogic } from '../experimentLogic'

/**
 * Hook to check if experiment data is stale and trigger refresh if needed.
 * Checks on mount and when page becomes visible after being hidden.
 *
 * This is a workaround to avoid kea race conditions when loading experiment data.
 * If we save the last refresh time at the experiment level this should go away.
 */
function useStaleDataCheck({
    lastRefresh,
    enabled,
    intervalSeconds,
    onRefresh,
}: {
    lastRefresh: string
    enabled: boolean
    intervalSeconds: number
    onRefresh: () => void
}): void {
    const hasCheckedOnMountRef = useRef(false)
    const pageWasHiddenRef = useRef(false)

    usePageVisibilityCb((isVisible) => {
        if (!isVisible) {
            pageWasHiddenRef.current = true
        }
    })

    useEffect(() => {
        // Only check on mount or after page was hidden and became visible again
        if (hasCheckedOnMountRef.current && !pageWasHiddenRef.current) {
            return
        }

        // Skip if disabled or no timestamp (but don't mark as checked yet)
        if (!enabled || !lastRefresh) {
            return
        }

        // Check if data is stale
        const secondsSinceRefresh = dayjs().diff(dayjs(lastRefresh), 'seconds')
        if (secondsSinceRefresh > intervalSeconds) {
            onRefresh()
        }

        // Only mark as checked after we've actually performed a check
        hasCheckedOnMountRef.current = true
        pageWasHiddenRef.current = false
    }, [lastRefresh, enabled, intervalSeconds, onRefresh])
}

export const ExperimentLastRefreshText = ({ lastRefresh }: { lastRefresh: string }): JSX.Element => {
    const colorClass = lastRefresh
        ? dayjs().diff(dayjs(lastRefresh), 'hours') > 12
            ? 'text-danger'
            : dayjs().diff(dayjs(lastRefresh), 'hours') > 6
              ? 'text-warning'
              : ''
        : ''

    return <span className={colorClass}>{lastRefresh ? <TZLabel time={lastRefresh} /> : 'a while ago'}</span>
}

const getExperimentRefreshIntervalSeconds = (): number[] => {
    if (process.env.NODE_ENV === 'development') {
        return [10, 300, 900, 1800] // 10s, 5min, 15min, 30min
    }
    return [300, 900, 1800] // 5min, 15min, 30min
}

const INTERVAL_OPTIONS = Array.from(getExperimentRefreshIntervalSeconds(), (value) => ({
    label: humanFriendlyDuration(value),
    value: value,
}))

export const ExperimentReloadAction = ({
    isRefreshing,
    lastRefresh,
    onClick,
}: {
    isRefreshing: boolean
    lastRefresh: string
    onClick: () => void
}): JSX.Element => {
    const { autoRefresh } = useValues(experimentLogic)
    const { setAutoRefresh, setPageVisibility, stopAutoRefreshInterval } = useActions(experimentLogic)

    // Check if data is stale on mount or when page becomes visible
    useStaleDataCheck({
        lastRefresh,
        enabled: autoRefresh.enabled,
        intervalSeconds: autoRefresh.interval,
        onRefresh: onClick,
    })

    // Memoize the page visibility callback to prevent unnecessary event listener churn
    const handlePageVisibilityChange = useCallback(
        (pageIsVisible: boolean) => {
            setPageVisibility(pageIsVisible)
        },
        [setPageVisibility]
    )

    usePageVisibilityCb(handlePageVisibilityChange)

    // Stop auto-refresh interval when component unmounts (e.g., navigating away)
    useEffect(() => {
        return () => {
            stopAutoRefreshInterval()
        }
    }, [stopAutoRefreshInterval])

    const options = INTERVAL_OPTIONS.map((option) => ({
        ...option,
        disabledReason: !autoRefresh.enabled ? 'Enable auto refresh to set the interval' : undefined,
    }))

    return (
        <div className="flex flex-col">
            <Label intent="menu">Last refreshed</Label>
            <div className="relative">
                <LemonButton
                    onClick={onClick}
                    type="secondary"
                    size="xsmall"
                    icon={isRefreshing ? <Spinner textColored /> : <IconRefresh />}
                    data-attr="refresh-experiment"
                    disabledReason={isRefreshing ? 'Loading...' : null}
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
                                                    onChange={(checked) =>
                                                        setAutoRefresh(checked, autoRefresh.interval)
                                                    }
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
                    {isRefreshing ? 'Loading…' : <ExperimentLastRefreshText lastRefresh={lastRefresh} />}
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
        </div>
    )
}
