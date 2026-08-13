import { useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import { SparklineData, projectTimezoneOf } from './hogInvocationsLogic'

interface InvocationsSparklineProps {
    data: SparklineData | null
    loading: boolean
    onDateRangeChange: (dateFrom: string, dateTo: string | undefined) => void
}

export function InvocationsSparkline({
    data,
    loading,
    onDateRangeChange,
}: InvocationsSparklineProps): JSX.Element | null {
    const [collapsed, setCollapsed] = useState(false)
    const { currentTeam } = useValues(teamLogic)
    // Buckets are cut in the project's timezone, so label them there too: in the viewer's zone a
    // project-local day can read as the day before. Resolved the same way the buckets are, or the
    // labels would fall back to UTC while the team is still loading and the bars would not.
    const projectTimezone = projectTimezoneOf(currentTeam)

    const { timeUnit, tickFormat } = useMemo(() => {
        const dates = data?.dates ?? []
        if (dates.length < 2) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        const hoursDiff = dayjs(dates[dates.length - 1]).diff(dayjs(dates[0]), 'hour')
        if (hoursDiff <= 6) {
            return { timeUnit: 'minute' as const, tickFormat: 'HH:mm' }
        }
        if (hoursDiff <= 48) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        return { timeUnit: 'day' as const, tickFormat: 'D MMM' }
    }, [data?.dates])

    const withXScale = useCallback(
        (scale: AnyScaleOptions): AnyScaleOptions =>
            ({
                ...scale,
                type: 'timeseries',
                ticks: {
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 6,
                    font: { size: 10, lineHeight: 1 },
                    callback: (value: string | number) => dayjs(value).tz(projectTimezone).format(tickFormat),
                },
                time: { unit: timeUnit },
            }) as AnyScaleOptions,
        [timeUnit, tickFormat, projectTimezone]
    )

    const onSelectionChange = useCallback(
        (sel: { startIndex: number; endIndex: number }): void => {
            const dates = data?.dates ?? []
            const from = dates[sel.startIndex]
            // `+1` so the selection end aligns with the *next* bucket boundary,
            // mirroring how the logs sparkline emits ranges. If we hit past
            // the end of the buckets, leave dateTo undefined (= "up to now").
            const to = dates[sel.endIndex + 1]
            if (from) {
                onDateRangeChange(from, to)
            }
        },
        [data?.dates, onDateRangeChange]
    )

    const labels = useMemo(() => (data?.dates ?? []).map((d) => dayjs(d).toISOString()), [data?.dates])
    const hasAnyData = (data?.series ?? []).some((s) => s.values.some((v) => v > 0))

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed(!collapsed)}
                    aria-expanded={!collapsed}
                >
                    <span className="text-xs text-muted">Volume over time</span>
                </LemonButton>
            </div>
            {!collapsed && (
                <div className="relative h-24">
                    {hasAnyData ? (
                        <Sparkline
                            labels={labels}
                            data={data!.series}
                            className="w-full h-full"
                            onSelectionChange={onSelectionChange}
                            withXScale={withXScale}
                            renderLabel={(label) => dayjs(label).tz(projectTimezone).format('D MMM YYYY HH:mm')}
                            hideZerosInTooltip
                            sortTooltipByCount
                        />
                    ) : !loading ? (
                        <div className="h-full text-muted text-xs flex items-center justify-center">
                            No invocations in this window
                        </div>
                    ) : null}
                    {loading && <SpinnerOverlay />}
                </div>
            )}
        </div>
    )
}
