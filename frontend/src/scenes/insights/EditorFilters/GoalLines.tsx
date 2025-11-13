import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { GoalLinesList } from 'lib/components/GoalLinesList'

import { InsightLogicProps } from '~/types'

import { goalLinesLogic } from './goalLinesLogic'

interface GoalLinesProps {
    insightProps: InsightLogicProps
}

export function GoalLines({ insightProps }: GoalLinesProps): JSX.Element {
    const { goalLines } = useValues(goalLinesLogic(insightProps))
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(goalLinesLogic(insightProps))

    return (
        <div className="mt-1 mb-2">
            <GoalLinesList goalLines={goalLines} removeGoalLine={removeGoalLine} updateGoalLine={updateGoalLine} />

            <LemonButton type="secondary" onClick={addGoalLine} icon={<IconPlusSmall />} sideIcon={null}>
                Add goal line
            </LemonButton>
        </div>
    )
}
