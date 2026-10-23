import { useActions, useValues } from 'kea'
import { useEffect, useId, useState } from 'react'

import { LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { FieldLabel, Switch, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { QuillDisplayOptionInfo } from '~/queries/nodes/InsightViz/QuillDisplayOptionInfo'
import { QuillDisplayOptionNumberInput } from '~/queries/nodes/InsightViz/QuillDisplayOptionNumberInput'
import { QuillDisplayOptionRow } from '~/queries/nodes/InsightViz/QuillDisplayOptionRow'

import { insightLogic } from '../insightLogic'

const BEGIN_AT_ZERO_INFO =
    'When off, the axis starts just below your lowest value instead of at zero, so small changes are easier to see.'

export function YAxisRangeFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, yAxisScaleType, showPercentStackView } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const [minDraft, setMinDraft] = useState(trendsFilter?.yAxisMin)
    const [maxDraft, setMaxDraft] = useState(trendsFilter?.yAxisMax)
    const beginAtZeroId = useId()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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
    // The minimum is hidden rather than cleared while the axis begins at zero, so the typed value
    // applies again when the toggle goes off.
    const beginsAtZero = trendsFilter?.yAxisStartAtZero !== false

    // An inverted pair sends the chart back to its automatic range, which otherwise just looks like
    // the controls not responding. Nothing to warn about while the minimum is disabled.
    const invalidRange =
        !beginsAtZero &&
        typeof trendsFilter?.yAxisMin === 'number' &&
        typeof trendsFilter?.yAxisMax === 'number' &&
        trendsFilter.yAxisMin >= trendsFilter.yAxisMax

    // Commit on blur, not on change: a number input reads as empty mid-entry, so every keystroke
    // would clear the bound. An emptied input reports NaN, which must become `undefined` because
    // the chart ignores NaN while the Options badge still counts it, leaving no way to clear it.
    const asBound = (value: number | undefined): number | undefined =>
        typeof value === 'number' && isFinite(value) ? value : undefined
    const commitMin = (): void => updateInsightFilter({ yAxisMin: asBound(minDraft) })
    const commitMax = (): void => updateInsightFilter({ yAxisMax: asBound(maxDraft) })
    const onBeginsAtZeroChange = (checked: boolean): void =>
        updateInsightFilter({ yAxisStartAtZero: checked ? undefined : false })

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <QuillDisplayOptionRow disabledReason={rangeDisabledReason}>
                    <FieldLabel htmlFor={beginAtZeroId} className="items-center gap-1 font-normal">
                        Begin at zero
                        <QuillDisplayOptionInfo info={BEGIN_AT_ZERO_INFO} />
                    </FieldLabel>
                    <Switch
                        id={beginAtZeroId}
                        size="sm"
                        data-attr="trends-y-axis-start-at-zero"
                        checked={beginsAtZero}
                        disabled={!!rangeDisabledReason}
                        onCheckedChange={onBeginsAtZeroChange}
                    />
                </QuillDisplayOptionRow>
                {!beginsAtZero && (
                    <QuillDisplayOptionNumberInput
                        label="Minimum"
                        data-attr="trends-y-axis-min-input"
                        value={minDraft}
                        placeholder="Auto"
                        disabledReason={rangeDisabledReason}
                        onChange={setMinDraft}
                        onCommit={commitMin}
                    />
                )}
                <QuillDisplayOptionNumberInput
                    label="Maximum"
                    data-attr="trends-y-axis-max-input"
                    value={maxDraft}
                    placeholder="Auto"
                    disabledReason={rangeDisabledReason}
                    onChange={setMaxDraft}
                    onCommit={commitMax}
                />
                {invalidRange && (
                    <Text size="xs" variant="destructive">
                        Maximum must be greater than minimum.
                    </Text>
                )}
            </div>
        )
    }

    return (
        <div className="p-1 px-2 flex flex-col gap-2">
            <LemonSwitch
                className="flex-1 w-full"
                label="Begin at zero"
                tooltip={BEGIN_AT_ZERO_INFO}
                data-attr="trends-y-axis-start-at-zero"
                checked={beginsAtZero}
                disabledReason={rangeDisabledReason}
                onChange={onBeginsAtZeroChange}
            />
            {!beginsAtZero && (
                <label className="flex items-center gap-2">
                    <span className="w-16 shrink-0">Minimum</span>
                    <LemonInput
                        type="number"
                        size="small"
                        className="w-0 flex-1"
                        data-attr="trends-y-axis-min-input"
                        value={minDraft}
                        placeholder="Auto"
                        disabledReason={rangeDisabledReason}
                        onChange={setMinDraft}
                        onBlur={commitMin}
                        onPressEnter={commitMin}
                    />
                </label>
            )}
            <label className="flex items-center gap-2">
                <span className="w-16 shrink-0">Maximum</span>
                <LemonInput
                    type="number"
                    size="small"
                    className="w-0 flex-1"
                    data-attr="trends-y-axis-max-input"
                    value={maxDraft}
                    placeholder="Auto"
                    disabledReason={rangeDisabledReason}
                    onChange={setMaxDraft}
                    onBlur={commitMax}
                    onPressEnter={commitMax}
                />
            </label>
            {invalidRange && <span className="text-xs text-danger">Maximum must be greater than minimum.</span>}
        </div>
    )
}
