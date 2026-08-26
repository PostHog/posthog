import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { DailyVolumePoint } from './autoresearchPipelineLogic'

// The h-40 track minus room for the count label above the tallest bar.
const BAR_MAX_HEIGHT_PX = 136

// Up to this many bars there is room to label each one; past it, counts live in
// the tooltips and only the endpoint dates render.
const PER_BAR_LABEL_LIMIT = 14

/** Bar-per-day chart of scoring volume, oldest day first. No chart deps, like ProbabilityHistogram. */
export function DailyVolumeChart({ points }: { points: DailyVolumePoint[] }): JSX.Element {
    const maxUsers = Math.max(...points.map((p) => p.users), 1)
    const labelEachBar = points.length <= PER_BAR_LABEL_LIMIT
    return (
        <div className="max-w-4xl">
            <div className="flex items-end gap-1">
                {points.map((p) => (
                    <Tooltip
                        key={p.day}
                        title={`${dayjs(p.day).format('MMM D, YYYY')}: ${p.users.toLocaleString()} users scored · ${p.avgProbabilityPct}% average probability`}
                    >
                        <div className="flex-1 min-w-0 max-w-16 flex flex-col items-center gap-0.5">
                            <div className="w-full h-40 flex flex-col items-center justify-end gap-0.5">
                                {labelEachBar && (
                                    <span className="text-xs tabular-nums text-secondary">
                                        {p.users.toLocaleString()}
                                    </span>
                                )}
                                <div
                                    className="w-full rounded-t bg-[var(--data-color-1)] hover:bg-[var(--data-color-1-hover)]"
                                    style={{
                                        height: Math.round((BAR_MAX_HEIGHT_PX * p.users) / maxUsers),
                                        minHeight: p.users > 0 ? 3 : 0,
                                    }}
                                />
                            </div>
                            {labelEachBar && (
                                <span className="text-xs text-muted whitespace-nowrap">
                                    {dayjs(p.day).format('MMM D')}
                                </span>
                            )}
                        </div>
                    </Tooltip>
                ))}
            </div>
            {!labelEachBar && (
                <div className="flex justify-between text-xs text-muted mt-1">
                    <span>{dayjs(points[0].day).format('MMM D')}</span>
                    <span>{dayjs(points[points.length - 1].day).format('MMM D')}</span>
                </div>
            )}
        </div>
    )
}
