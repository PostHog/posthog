import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { BAR_DISPLAYS, displayMatches } from '~/queries/nodes/InsightViz/displayTypes'

import { insightLogic } from '../insightLogic'

export function YAxisRangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, display, yAxisScaleType, showPercentStackView } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const [minDraft, setMinDraft] = useState(trendsFilter?.yAxisMin)
    const [maxDraft, setMaxDraft] = useState(trendsFilter?.yAxisMax)

    useEffect(() => {
        setMinDraft(trendsFilter?.yAxisMin)
    }, [trendsFilter?.yAxisMin])

    useEffect(() => {
        setMaxDraft(trendsFilter?.yAxisMax)
    }, [trendsFilter?.yAxisMax])

    const rangeDisabledReason =
        yAxisScaleType === 'log10'
            ? 'Not available on a logarithmic scale'
            : showPercentStackView
              ? 'Not available while showing percentages'
              : undefined
    const startAtZeroDisabledReason = displayMatches(display, BAR_DISPLAYS)
        ? 'Bar charts always begin at zero'
        : rangeDisabledReason

    // The chart falls back to its automatic range while the pair is inverted, so say why rather
    // than leaving the controls looking unresponsive.
    const invalidRange =
        typeof trendsFilter?.yAxisMin === 'number' &&
        typeof trendsFilter?.yAxisMax === 'number' &&
        trendsFilter.yAxisMin >= trendsFilter.yAxisMax

    // Committing on blur rather than on change keeps a half-typed value out of the query — the
    // number input reads as empty mid-entry, which on every keystroke would clear the bound.
    const commitMin = (): void => updateInsightFilter({ yAxisMin: minDraft })
    const commitMax = (): void => updateInsightFilter({ yAxisMax: maxDraft })

    return (
        <div className="p-1 px-2 flex flex-col gap-2 w-64">
            <LemonSwitch
                className="flex-1 w-full"
                label="Begin at zero"
                tooltip="When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see."
                data-attr="trends-y-axis-start-at-zero"
                checked={trendsFilter?.yAxisStartAtZero !== false}
                disabledReason={startAtZeroDisabledReason}
                onChange={(checked) => updateInsightFilter({ yAxisStartAtZero: checked ? undefined : false })}
            />
            <div className="flex flex-col gap-1">
                <LemonLabel>Minimum</LemonLabel>
                <LemonInput
                    type="number"
                    size="small"
                    data-attr="trends-y-axis-min-input"
                    value={minDraft}
                    placeholder="Auto"
                    disabledReason={rangeDisabledReason}
                    onChange={setMinDraft}
                    onBlur={commitMin}
                    onPressEnter={commitMin}
                />
            </div>
            <div className="flex flex-col gap-1">
                <LemonLabel>Maximum</LemonLabel>
                <LemonInput
                    type="number"
                    size="small"
                    data-attr="trends-y-axis-max-input"
                    value={maxDraft}
                    placeholder="Auto"
                    disabledReason={rangeDisabledReason}
                    onChange={setMaxDraft}
                    onBlur={commitMax}
                    onPressEnter={commitMax}
                />
            </div>
            {invalidRange ? (
                <span className="text-xs text-danger">Maximum must be greater than minimum.</span>
            ) : (
                <span className="text-xs text-secondary">Leave blank for an automatic bound.</span>
            )}
        </div>
    )
}
