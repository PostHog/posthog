import { useActions, useValues } from 'kea'

import { LemonColorButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from '@posthog/query-frontend/nodes/TrendsQuery/trendsDataLogic'
import { IndexedTrendResult } from '@posthog/query-frontend/nodes/TrendsQuery/types'

import { resultCustomizationsModalLogic } from '@posthog/query-frontend/nodes/InsightViz/resultCustomizationsModalLogic'

export function ColorCustomizationColumnTitle(): JSX.Element {
    return <>Color</>
}

export function ColorCustomizationColumnItem({ item }: { item: IndexedTrendResult }): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { getTrendsColor } = useValues(trendsDataLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    const color = getTrendsColor(item)

    return (
        <LemonColorButton
            color={color}
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()

                openModal(item)
            }}
            type="tertiary"
            size="small"
            disabledReason={editingDisabledReason}
        />
    )
}
