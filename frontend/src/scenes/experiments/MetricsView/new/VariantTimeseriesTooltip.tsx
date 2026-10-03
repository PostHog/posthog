import { useValues } from 'kea'

import { IconClock, IconHome, IconLaptop } from '@posthog/icons'
import { TooltipFooter, TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { IconWeb } from 'lib/lemon-ui/icons'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'

const DATE_FORMAT = 'MMM D, YYYY'
const DATETIME_FORMAT = 'MMM D, YYYY h:mm A'

const formatPercent = (value: number | null): string =>
    value === null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(2)}%`

export interface VariantTimeseriesTooltipProps {
    date: string
    delta: number | null
    lowerBound: number | null
    upperBound: number | null
    isRatioMetric: boolean
    exposures?: number
    denominator?: number
    significant?: boolean
    hasRealData: boolean
    /** When the timeseries was computed (ISO string), or null if unknown. */
    computedAt: string | null
    /** The variant line's color, shown as the header swatch. */
    color: string
}

function TooltipRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4">
            <span className="opacity-60">{label}</span>
            <strong className="tabular-nums">{value}</strong>
        </div>
    )
}

function TimezoneRow({
    icon,
    label,
    caption,
    value,
}: {
    icon: React.ReactNode
    label: string
    caption?: string
    value: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-1.5">
            <span className="opacity-60 shrink-0">{icon}</span>
            <span className="opacity-60">{label}</span>
            {caption && <span className="opacity-40">{caption}</span>}
            <strong className="ml-auto tabular-nums">{value}</strong>
        </div>
    )
}

/**
 * Tooltip body for the variant timeseries chart, returned from the chart's `tooltip` render prop.
 * Everything below the date is per-point metadata rather than per-series values, so quill's
 * `DefaultTooltip` — one row per series — cannot express it.
 */
export function VariantTimeseriesTooltip({
    date,
    delta,
    lowerBound,
    upperBound,
    isRatioMetric,
    exposures,
    denominator,
    significant,
    hasRealData,
    computedAt,
    color,
}: VariantTimeseriesTooltipProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const computed = computedAt ? dayjs(computedAt) : null
    const projectTimezone = currentTeam?.timezone
    const computedDate = computed?.toDate()

    return (
        <TooltipSurface>
            <div className="flex items-center gap-2 font-semibold mb-1">
                <TooltipSwatch color={color} />
                <span className="truncate">{dayjs(date).format(DATE_FORMAT)}</span>
            </div>

            <TooltipRow label="Delta" value={formatPercent(delta)} />
            <TooltipRow
                label="Confidence interval"
                value={`${formatPercent(lowerBound)} → ${formatPercent(upperBound)}`}
            />
            {isRatioMetric
                ? denominator !== undefined && <TooltipRow label="Denominator" value={denominator.toLocaleString()} />
                : exposures !== undefined && <TooltipRow label="Exposures" value={exposures.toLocaleString()} />}
            {significant !== undefined && (
                <TooltipRow
                    label="Significant"
                    value={
                        <span className={significant ? 'text-success' : undefined}>{significant ? 'Yes' : 'No'}</span>
                    }
                />
            )}

            {!hasRealData && (
                <TooltipFooter>
                    <span className="flex items-center justify-center gap-1.5">
                        <IconClock className="shrink-0" />
                        Data pending — showing last known value
                    </span>
                </TooltipFooter>
            )}

            {computed && (
                <div className="mt-1 pt-1 border-t border-current/25 flex flex-col gap-0.5">
                    <div className="opacity-50 uppercase tracking-wide font-semibold text-[0.6875rem]">
                        Calculated at
                    </div>
                    {projectTimezone && (
                        <TimezoneRow
                            icon={<IconHome />}
                            label="Project"
                            caption={shortTimeZone(projectTimezone, computedDate) ?? projectTimezone}
                            value={computed.tz(projectTimezone).format(DATETIME_FORMAT)}
                        />
                    )}
                    <TimezoneRow
                        icon={<IconLaptop />}
                        label="Your device"
                        caption={shortTimeZone(undefined, computedDate) ?? ''}
                        value={computed.format(DATETIME_FORMAT)}
                    />
                    {projectTimezone !== 'UTC' && (
                        <TimezoneRow
                            icon={<IconWeb />}
                            label="UTC"
                            caption="UTC"
                            value={computed.tz('UTC').format(DATETIME_FORMAT)}
                        />
                    )}
                </div>
            )}
        </TooltipSurface>
    )
}
