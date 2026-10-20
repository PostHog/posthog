import { useActions, useValues } from 'kea'

import { GoalLinesList } from 'lib/components/GoalLinesList'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { InsightLogicProps } from '~/types'

import { goalLinesLogic } from './goalLinesLogic'
import { LemonAddGoalLineButton } from './LemonAddGoalLineButton'
import { QuillAddGoalLineButton } from './QuillAddGoalLineButton'

interface GoalLinesProps {
    insightProps: InsightLogicProps
}

export function GoalLines({ insightProps }: GoalLinesProps): JSX.Element {
    const { goalLines } = useValues(goalLinesLogic(insightProps))
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(goalLinesLogic(insightProps))
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    const className = goalLines.length > 0 ? 'mt-2' : ''

    return (
        <div>
            <GoalLinesList goalLines={goalLines} removeGoalLine={removeGoalLine} updateGoalLine={updateGoalLine} />
            {quillEnabled ? (
                <QuillAddGoalLineButton onClick={addGoalLine} className={className} />
            ) : (
                <LemonAddGoalLineButton onClick={addGoalLine} className={className} />
            )}
        </div>
    )
}
