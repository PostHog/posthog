import { LemonButton, LemonModal, LemonTable, LemonTableColumns, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { formatBreakdownLabel, getFunnelDatasetKey, getTrendDatasetKey } from 'scenes/insights/utils'

import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { dashboardInsightColorsLogic } from './dashboardInsightColorsLogic'
import { ColorResult, GithubPicker, TwitterPicker } from 'react-color'
import { ColorGlyph } from 'lib/components/SeriesGlyph'
import { useState } from 'react'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

function extractBreakdownValues(insightTiles: DashboardTile<QueryBasedInsightModel>[] | null): string[] {
    if (insightTiles == null) {
        return []
    }

    return insightTiles
        .flatMap((tile) => {
            if (isInsightVizNode(tile.insight?.query)) {
                if (isFunnelsQuery(tile.insight.query.source)) {
                    return tile.insight?.result.map((result) => {
                        const key = getFunnelDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        return keyParts['breakdown_value']
                    })
                } else if (isTrendsQuery(tile.insight.query.source)) {
                    return tile.insight?.result.map((result: any) => {
                        const key = getTrendDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        return keyParts['breakdown_value']
                    })
                }
                return []
            }
            return []
        })
        .filter((value) => value != null)
        .sort()
}

type ColorPickerButtonProps = {
    // color: string
    // onColorSelect?: (color: string) => void
    // colorChoices?: string[]
}

export const ColorPickerButton = ({}: // color,
// onColorSelect: propOnColorSelect,
// colorChoices = DEFAULT_PICKER_COLORS,
ColorPickerButtonProps): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)
    const color = '#000000'
    const colors = [
        '#000000',
        '#111111',
        '#222222',
        '#333333',
        '#444444',
        '#555555',
        '#666666',
        '#777777',
        '#888888',
        '#999999',
        '#aaaaaa',
        '#bbbbbb',
        '#cccccc',
        '#dddddd',
        '#eeeeee',
    ]
    const onColorSelect = (colorResult: ColorResult): void => {
        console.log(colorResult)
    }
    // const [pickerOpen, setPickerOpen] = useState(false)
    // const { isDarkModeOn } = useValues(themeLogic)

    // const onColorSelect = (colorResult: ColorResult): void => {
    //     if (propOnColorSelect) {
    //         propOnColorSelect(colorResult.hex)
    //     }

    //     if (colorChoices.includes(colorResult.hex)) {
    //         setPickerOpen(false)
    //     }
    // }

    // const colors = isDarkModeOn ? colorChoices.map((n) => RGBToHex(lightenDarkenColor(n, -30))) : colorChoices

    return (
        <Popover
            visible={isOpen}
            overlay={<GithubPicker color={color} colors={colors} onChangeComplete={onColorSelect} />}
            onClickOutside={() => setIsOpen(false)}
            padded={false}
        >
            <LemonButton
                type="tertiary"
                onClick={() => setIsOpen(!isOpen)}
                // sideIcon={<></>}
                // className="ConditionalFormattingTab__ColorPicker"
            >
                <ColorGlyph color={color} />
            </LemonButton>
        </Popover>
    )
}

export function DashboardInsightColorsModal(): JSX.Element {
    const { dashboardInsightColorsModalVisible, insightTiles, insightTilesLoading } =
        useValues(dashboardInsightColorsLogic)
    const { hideDashboardInsightColorsModal } = useActions(dashboardInsightColorsLogic)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { cohorts } = useValues(cohortsModel)

    const breakdownValues = extractBreakdownValues(insightTiles)

    const columns: LemonTableColumns<string[]> = [
        {
            title: 'Color',
            key: 'color',
            render: (_, breakdownValue) => {
                return <ColorPickerButton />
            },
        },
        {
            title: 'Breakdown',
            key: 'breakdown_value',
            // width: 0,
            render: (_, breakdownValue) => {
                // TODO: support for cohorts and nested breakdowns
                const breakdownFilter = {}
                const breakdownLabel = formatBreakdownLabel(
                    breakdownValue,
                    breakdownFilter,
                    cohorts?.results,
                    formatPropertyValueForDisplay
                )
                const formattedLabel = stringWithWBR(breakdownLabel, 20)

                return <span>{formattedLabel}</span>
            },
        },
    ]

    return (
        <LemonModal
            title="Customize Colors"
            isOpen={dashboardInsightColorsModalVisible}
            onClose={hideDashboardInsightColorsModal}
        >
            {insightTilesLoading ? (
                <div className="flex flex-col items-center">
                    {/* Slightly offset to the left for visual balance. */}
                    <Animation type={AnimationType.SportsHog} size="large" className="-ml-4" />
                    <p className="text-primary">Waiting for dashboard tiles to load and refresh…</p>
                </div>
            ) : (
                <>
                    <LemonTable columns={columns} dataSource={breakdownValues} loading={insightTilesLoading} />
                </>
            )}
        </LemonModal>
    )
}
