// PROTOTYPE — small pieces shared by the property usage variants.
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { DataSource } from './propertyUsageMock'

/** Marks where a figure would come from, so the variants double as a backend shopping list. */
export function SourceTag({ source }: { source: DataSource }): JSX.Element {
    return source === 'pr' ? (
        <Tooltip title="Already provided by PR 82610">
            <LemonTag size="small" type="success">
                PR
            </LemonTag>
        </Tooltip>
    ) : (
        <Tooltip title="Needs more backend work than PR 82610 provides">
            <LemonTag size="small" type="warning">
                new
            </LemonTag>
        </Tooltip>
    )
}

export function DailyBars({ daily, height = 40 }: { daily: number[]; height?: number }): JSX.Element {
    const max = Math.max(1, ...daily)
    return (
        <div className="flex items-end gap-px w-full" style={{ height }}>
            {daily.map((value, i) => (
                <Tooltip
                    key={i}
                    title={`${dayjs()
                        .subtract(29 - i, 'day')
                        .format('MMM D')}: ${value.toLocaleString()} queries`}
                >
                    <div
                        className={value ? 'flex-1 bg-accent rounded-t-xs' : 'flex-1 bg-border rounded-t-xs'}
                        style={{ height: value ? `${Math.max(4, (value / max) * 100)}%` : 2 }}
                    />
                </Tooltip>
            ))}
        </div>
    )
}
