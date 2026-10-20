import { LemonColorGlyph, LemonColorPicker } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { GoalLine } from '~/queries/schema/schema-general'

import { LemonGoalLinesList } from './LemonGoalLinesList'
import { QuillGoalLinesList } from './QuillGoalLinesList'

export interface GoalLinesListProps {
    allowCalculations?: boolean
    calculationDisabledReason?: string
    goalLines: GoalLine[]
    updateGoalLine: (
        goalLineIndex: number,
        key: keyof GoalLine,
        value: NonNullable<string | number | boolean | undefined>
    ) => void
    removeGoalLine: (goalLineIndex: number) => void
}

export function GoalLinesList(props: GoalLinesListProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const seriesColor = getSeriesColorPalette()
    if (!quillEnabled) {
        return <LemonGoalLinesList {...props} />
    }
    return (
        <QuillGoalLinesList
            {...props}
            renderColorPicker={(goalLineIndex, borderColor) => (
                <LemonColorPicker
                    colors={seriesColor}
                    selectedColor={borderColor || undefined}
                    onSelectColor={(color) => props.updateGoalLine(goalLineIndex, 'borderColor', color)}
                    showCustomColor
                    customButton={
                        <div className="cursor-pointer">
                            <LemonColorGlyph color={borderColor} size="small" />
                        </div>
                    }
                />
            )}
        />
    )
}
