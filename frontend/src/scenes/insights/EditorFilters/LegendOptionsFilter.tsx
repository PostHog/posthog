import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'
import { QuillDisplayOptionSelect } from '~/queries/nodes/InsightViz/QuillDisplayOptionSelect'
import type { TrendsFilter } from '~/queries/schema/schema-general'

import { insightVizDataLogic } from '../insightVizDataLogic'

type LegendPosition = NonNullable<TrendsFilter['legendPosition']>

const POSITION_OPTIONS: { value: LegendPosition; label: string }[] = [
    { value: 'bottom', label: 'Bottom' },
    { value: 'top', label: 'Top' },
    { value: 'left', label: 'Left' },
    { value: 'right', label: 'Right' },
]

export function LegendOptionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showLegend, legendPosition } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const onShowLegendChange = (checked: boolean): void =>
        updateInsightFilter({
            showLegend: checked,
            // Seed bottom on first enable — old insights without a saved position render right (chart-config fallback).
            ...(checked && legendPosition == null ? { legendPosition: 'bottom' } : {}),
        })
    const position = (legendPosition ?? (showLegend ? 'right' : 'bottom')) as LegendPosition
    const positionDisabledReason = !showLegend ? 'Enable the legend to set its position' : undefined
    const onPositionChange = (next: LegendPosition): void => updateInsightFilter({ legendPosition: next })

    if (todayRailNav) {
        return (
            <div className="flex items-center justify-between gap-2">
                <DisplayOptionCheckbox label="Show legend" checked={!!showLegend} onChange={onShowLegendChange} />
                <QuillDisplayOptionSelect
                    value={position}
                    options={POSITION_OPTIONS}
                    disabledReason={positionDisabledReason}
                    onChange={onPositionChange}
                />
            </div>
        )
    }

    return (
        <div className="flex items-center justify-between gap-2 p-1 px-2">
            <LemonCheckbox
                onChange={onShowLegendChange}
                checked={!!showLegend}
                label={<span className="font-normal">Show legend</span>}
                size="small"
            />
            <LemonSelect
                size="small"
                value={position}
                options={POSITION_OPTIONS}
                disabledReason={positionDisabledReason}
                onChange={onPositionChange}
            />
        </div>
    )
}
