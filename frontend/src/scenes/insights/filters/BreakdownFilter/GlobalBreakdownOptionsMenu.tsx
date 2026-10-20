import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { LemonGlobalBreakdownOptionsMenu } from './LemonGlobalBreakdownOptionsMenu'
import { QuillGlobalBreakdownOptionsMenu } from './QuillGlobalBreakdownOptionsMenu'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

export const MIN_BREAKDOWN_LIMIT = 1
export const MAX_BREAKDOWN_LIMIT = 1000

export interface BreakdownOptionsProps {
    isTrends: boolean
    breakdownLimit: number
    breakdownHideOtherAggregation: boolean
    setBreakdownHideOtherAggregation: (hide: boolean) => void
    /** Clamps the input's draft and commits it, or restores the last limit when the draft is empty. */
    onCommitLimit: (target: HTMLInputElement) => void
}

export const GlobalBreakdownOptionsMenu = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isTrends } = useValues(insightVizDataLogic(insightProps))
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')

    const { breakdownLimit, breakdownHideOtherAggregation, breakdownFilter } = useValues(taxonomicBreakdownFilterLogic)
    const { setBreakdownLimit, setBreakdownHideOtherAggregation } = useActions(taxonomicBreakdownFilterLogic)

    // Cohort breakdowns are over an explicit, user-picked set — there's no long-tail to truncate
    // and nothing to bucket as "Other", so these controls don't apply.
    if (breakdownFilter?.breakdown_type === 'cohort') {
        return null
    }

    const onCommitLimit = (target: HTMLInputElement): void => {
        const raw = target.value
        if (raw === '') {
            // Don't commit an empty value — restore the last
            // committed limit instead.
            target.value = String(breakdownLimit)
            return
        }
        const clamped = Math.min(Math.max(Number(raw), MIN_BREAKDOWN_LIMIT), MAX_BREAKDOWN_LIMIT)
        target.value = String(clamped)
        if (clamped !== breakdownLimit) {
            setBreakdownLimit(clamped)
        }
    }

    const props: BreakdownOptionsProps = {
        isTrends,
        breakdownLimit,
        breakdownHideOtherAggregation: !!breakdownHideOtherAggregation,
        setBreakdownHideOtherAggregation,
        onCommitLimit,
    }
    return quillEnabled ? (
        <QuillGlobalBreakdownOptionsMenu {...props} />
    ) : (
        <LemonGlobalBreakdownOptionsMenu {...props} />
    )
}
