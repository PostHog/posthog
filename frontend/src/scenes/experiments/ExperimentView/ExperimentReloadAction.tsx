import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

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

import { EXPERIMENT_REFRESH_INTERVAL_SECONDS } from '../constants'
import { experimentLogic } from '../experimentLogic'

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

const INTERVAL_OPTIONS = Array.from(EXPERIMENT_REFRESH_INTERVAL_SECONDS, (value) => ({
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

    usePageVisibilityCb((pageIsVisible) => {
        setPageVisibility(pageIsVisible)
    })

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
