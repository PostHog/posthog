import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ColorGlyph } from 'lib/components/SeriesGlyph'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { resultCustomizationsModalLogic } from '~/queries/nodes/InsightViz/resultCustomizationsModalLogic'

type CustomizationIconProps = {
    color?: string
}

export const CustomizationIcon = ({ color }: CustomizationIconProps): JSX.Element | null => {
    return (
        <div className="w-4 h-4 flex">
            <ColorGlyph color={color} className="w-4 h-4" />
        </div>
    )
}

export function ColorCustomizationColumnTitle(): JSX.Element {
    return <>Color</>
}

export function ColorCustomizationColumnItem({ item }: { item: IndexedTrendResult }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { getTrendsColor } = useValues(trendsDataLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    const color = getTrendsColor(item)

    return (
        <LemonButton
            onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()

                openModal(item)
            }}
            size="small"
        >
            <CustomizationIcon isVisible={true} color={color} />
        </LemonButton>
    )
}
