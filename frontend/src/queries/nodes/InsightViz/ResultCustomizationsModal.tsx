import './ResultCustomizationsModal.scss'

import { LemonButton, LemonButtonProps, LemonModal } from '@posthog/lemon-ui'
import assert from 'assert'
import { useActions, useValues } from 'kea'
import { DataColorToken } from 'lib/colors'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { ColorGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGB } from 'lib/utils'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ResultCustomizationBy } from '~/queries/schema/schema-general'
import { FlattenedFunnelStepByBreakdown } from '~/types'

import { resultCustomizationsModalLogic } from './resultCustomizationsModalLogic'

export function ResultCustomizationsModal(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)

    const { modalVisible, dataset, colorToken, resultCustomizationBy } = useValues(
        resultCustomizationsModalLogic(insightProps)
    )
    const { closeModal, setColorToken, save } = useActions(resultCustomizationsModalLogic(insightProps))

    const { isTrends, isFunnels, querySource } = useValues(insightVizDataLogic)

    const { getTheme } = useValues(dataThemeLogic)
    const theme = getTheme(querySource?.dataColorTheme)

    if (dataset == null || theme == null) {
        return null
    }

    return (
        <LemonModal
            data-attr="legend-entry-modal"
            isOpen={modalVisible}
            title="Customize result color"
            width={520}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={save}>
                        Save customizations
                    </LemonButton>
                </>
            }
            onClose={closeModal}
        >
            <p>
                Query results can be customized to provide a more{' '}
                <strong>meaningful appearance for you and your team members</strong>. The customizations are also shown
                on dashboards.
            </p>
            {isTrends && (
                <TrendsInfo dataset={dataset as IndexedTrendResult} resultCustomizationBy={resultCustomizationBy} />
            )}
            {isFunnels && <FunnelsInfo dataset={dataset as FlattenedFunnelStepByBreakdown} />}

            <h3 className="l4 mt-2 mb-2">Color</h3>
            <div className="flex flex-wrap gap-1">
                {Object.keys(theme).map((key) => (
                    <ColorGlyphButton
                        key={key as DataColorToken}
                        colorToken={key as DataColorToken}
                        selected={key === colorToken}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            setColorToken(key as DataColorToken)
                        }}
                    />
                ))}
            </div>
        </LemonModal>
    )
}

type TrendsInfoProps = {
    dataset: IndexedTrendResult
    resultCustomizationBy: ResultCustomizationBy
}

function TrendsInfo({ dataset, resultCustomizationBy }: TrendsInfoProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { breakdownFilter } = useValues(insightVizDataLogic)

    return (
        <>
            {dataset.breakdown_value ? (
                <p className="mb-2">
                    You are customizing the appearance of series{' '}
                    <b>
                        <EntityFilterInfo filter={dataset.action} allowWrap={true} showSingleName={true} />
                    </b>{' '}
                    for the breakdown{' '}
                    <b>
                        {formatBreakdownLabel(
                            dataset.breakdown_value,
                            breakdownFilter,
                            cohorts,
                            formatPropertyValueForDisplay
                        )}
                    </b>
                    .
                </p>
            ) : (
                <p className="mb-2">
                    You are customizing the appearance of series{' '}
                    <b>
                        <EntityFilterInfo filter={dataset.action} allowWrap={true} showSingleName={true} />
                    </b>
                    .
                </p>
            )}

            <p>
                Results are assigned by{' '}
                {resultCustomizationBy === ResultCustomizationBy.Position ? (
                    <>
                        their <strong>rank</strong> in the dataset
                    </>
                ) : (
                    <>
                        their <strong>name</strong> in the dataset
                    </>
                )}
                . You can change this in insight settings.
            </p>
        </>
    )
}

type FunnelsInfoProps = {
    dataset: FlattenedFunnelStepByBreakdown
}

function FunnelsInfo({ dataset }: FunnelsInfoProps): JSX.Element {
    return (
        <>
            You are customizing the appearance of the{' '}
            {dataset.breakdown_value?.[0] === 'Baseline' ? (
                <b>Baseline</b>
            ) : (
                <>
                    <b>{dataset.breakdown_value?.[0]}</b> breakdown
                </>
            )}
            .
        </>
    )
}

type ColorGlyphButtonProps = {
    colorToken: DataColorToken
    selected: boolean
    onClick: LemonButtonProps['onClick']
}

function ColorGlyphButton({ colorToken, selected, onClick }: ColorGlyphButtonProps): JSX.Element {
    const { getTheme } = useValues(dataThemeLogic)

    const { querySource } = useValues(insightVizDataLogic)

    const theme = getTheme(querySource?.dataColorTheme)
    const color = theme?.[colorToken] as string

    return (
        <LemonButton
            type={selected ? 'secondary' : 'tertiary'}
            className="ResultCustomizationsModal__ColorGlyphButton"
            onClick={onClick}
            tooltip={colorDescription(color)}
        >
            <ColorGlyph color={color} />
        </LemonButton>
    )
}

type ReferenceColor = { name: string; group: string }

/** HTML5 colors */
const referenceColors: Record<string, ReferenceColor> = {
    '#FFC0CB': { name: 'Pink', group: 'Pink' },
    '#FFB6C1': { name: 'LightPink', group: 'Pink' },
    '#FF69B4': { name: 'HotPink', group: 'Pink' },
    '#FF1493': { name: 'DeepPink', group: 'Pink' },
    '#DB7093': { name: 'PaleVioletRed', group: 'Pink' },
    '#C71585': { name: 'MediumVioletRed', group: 'Pink' },
    '#E6E6FA': { name: 'Lavender', group: 'Purple' },
    '#D8BFD8': { name: 'Thistle', group: 'Purple' },
    '#DDA0DD': { name: 'Plum', group: 'Purple' },
    '#DA70D6': { name: 'Orchid', group: 'Purple' },
    '#EE82EE': { name: 'Violet', group: 'Purple' },
    '#FF00FF': { name: 'Magenta', group: 'Purple' },
    '#BA55D3': { name: 'MediumOrchid', group: 'Purple' },
    '#9932CC': { name: 'DarkOrchid', group: 'Purple' },
    '#9400D3': { name: 'DarkViolet', group: 'Purple' },
    '#8A2BE2': { name: 'BlueViolet', group: 'Purple' },
    '#8B008B': { name: 'DarkMagenta', group: 'Purple' },
    '#800080': { name: 'Purple', group: 'Purple' },
    '#9370DB': { name: 'MediumPurple', group: 'Purple' },
    '#7B68EE': { name: 'MediumSlateBlue', group: 'Purple' },
    '#6A5ACD': { name: 'SlateBlue', group: 'Purple' },
    '#483D8B': { name: 'DarkSlateBlue', group: 'Purple' },
    '#663399': { name: 'RebeccaPurple', group: 'Purple' },
    '#4B0082': { name: 'Indigo', group: 'Purple' },
    '#FFA07A': { name: 'LightSalmon', group: 'Red' },
    '#FA8072': { name: 'Salmon', group: 'Red' },
    '#E9967A': { name: 'DarkSalmon', group: 'Red' },
    '#F08080': { name: 'LightCoral', group: 'Red' },
    '#CD5C5C': { name: 'IndianRed', group: 'Red' },
    '#DC143C': { name: 'Crimson', group: 'Red' },
    '#FF0000': { name: 'Red', group: 'Red' },
    '#B22222': { name: 'FireBrick', group: 'Red' },
    '#8B0000': { name: 'DarkRed', group: 'Red' },
    '#FFA500': { name: 'Orange', group: 'Orange' },
    '#FF8C00': { name: 'DarkOrange', group: 'Orange' },
    '#FF7F50': { name: 'Coral', group: 'Orange' },
    '#FF6347': { name: 'Tomato', group: 'Orange' },
    '#FF4500': { name: 'OrangeRed', group: 'Orange' },
    '#FFD700': { name: 'Gold', group: 'Yellow' },
    '#FFFF00': { name: 'Yellow', group: 'Yellow' },
    '#FFFFE0': { name: 'LightYellow', group: 'Yellow' },
    '#FFFACD': { name: 'LemonChiffon', group: 'Yellow' },
    '#FAFAD2': { name: 'LightGoldenRodYellow', group: 'Yellow' },
    '#FFEFD5': { name: 'PapayaWhip', group: 'Yellow' },
    '#FFE4B5': { name: 'Moccasin', group: 'Yellow' },
    '#FFDAB9': { name: 'PeachPuff', group: 'Yellow' },
    '#EEE8AA': { name: 'PaleGoldenRod', group: 'Yellow' },
    '#F0E68C': { name: 'Khaki', group: 'Yellow' },
    '#BDB76B': { name: 'DarkKhaki', group: 'Yellow' },
    '#ADFF2F': { name: 'GreenYellow', group: 'Green' },
    '#7FFF00': { name: 'Chartreuse', group: 'Green' },
    '#7CFC00': { name: 'LawnGreen', group: 'Green' },
    '#00FF00': { name: 'Lime', group: 'Green' },
    '#32CD32': { name: 'LimeGreen', group: 'Green' },
    '#98FB98': { name: 'PaleGreen', group: 'Green' },
    '#90EE90': { name: 'LightGreen', group: 'Green' },
    '#00FA9A': { name: 'MediumSpringGreen', group: 'Green' },
    '#00FF7F': { name: 'SpringGreen', group: 'Green' },
    '#3CB371': { name: 'MediumSeaGreen', group: 'Green' },
    '#2E8B57': { name: 'SeaGreen', group: 'Green' },
    '#228B22': { name: 'ForestGreen', group: 'Green' },
    '#008000': { name: 'Green', group: 'Green' },
    '#006400': { name: 'DarkGreen', group: 'Green' },
    '#9ACD32': { name: 'YellowGreen', group: 'Green' },
    '#6B8E23': { name: 'OliveDrab', group: 'Green' },
    '#556B2F': { name: 'DarkOliveGreen', group: 'Green' },
    '#66CDAA': { name: 'MediumAquaMarine', group: 'Green' },
    '#8FBC8F': { name: 'DarkSeaGreen', group: 'Green' },
    '#20B2AA': { name: 'LightSeaGreen', group: 'Green' },
    '#008B8B': { name: 'DarkCyan', group: 'Green' },
    '#008080': { name: 'Teal', group: 'Green' },
    '#00FFFF': { name: 'Cyan', group: 'Cyan' },
    '#E0FFFF': { name: 'LightCyan', group: 'Cyan' },
    '#AFEEEE': { name: 'PaleTurquoise', group: 'Cyan' },
    '#7FFFD4': { name: 'Aquamarine', group: 'Cyan' },
    '#40E0D0': { name: 'Turquoise', group: 'Cyan' },
    '#48D1CC': { name: 'MediumTurquoise', group: 'Cyan' },
    '#00CED1': { name: 'DarkTurquoise', group: 'Cyan' },
    '#5F9EA0': { name: 'CadetBlue', group: 'Blue' },
    '#4682B4': { name: 'SteelBlue', group: 'Blue' },
    '#B0C4DE': { name: 'LightSteelBlue', group: 'Blue' },
    '#ADD8E6': { name: 'LightBlue', group: 'Blue' },
    '#B0E0E6': { name: 'PowderBlue', group: 'Blue' },
    '#87CEFA': { name: 'LightSkyBlue', group: 'Blue' },
    '#87CEEB': { name: 'SkyBlue', group: 'Blue' },
    '#6495ED': { name: 'CornflowerBlue', group: 'Blue' },
    '#00BFFF': { name: 'DeepSkyBlue', group: 'Blue' },
    '#1E90FF': { name: 'DodgerBlue', group: 'Blue' },
    '#4169E1': { name: 'RoyalBlue', group: 'Blue' },
    '#0000FF': { name: 'Blue', group: 'Blue' },
    '#0000CD': { name: 'MediumBlue', group: 'Blue' },
    '#00008B': { name: 'DarkBlue', group: 'Blue' },
    '#000080': { name: 'Navy', group: 'Blue' },
    '#191970': { name: 'MidnightBlue', group: 'Blue' },
    '#FFF8DC': { name: 'Cornsilk', group: 'Brown' },
    '#FFEBCD': { name: 'BlanchedAlmond', group: 'Brown' },
    '#FFE4C4': { name: 'Bisque', group: 'Brown' },
    '#FFDEAD': { name: 'NavajoWhite', group: 'Brown' },
    '#F5DEB3': { name: 'Wheat', group: 'Brown' },
    '#DEB887': { name: 'BurlyWood', group: 'Brown' },
    '#D2B48C': { name: 'Tan', group: 'Brown' },
    '#BC8F8F': { name: 'RosyBrown', group: 'Brown' },
    '#F4A460': { name: 'SandyBrown', group: 'Brown' },
    '#DAA520': { name: 'GoldenRod', group: 'Brown' },
    '#B8860B': { name: 'DarkGoldenRod', group: 'Brown' },
    '#CD853F': { name: 'Peru', group: 'Brown' },
    '#D2691E': { name: 'Chocolate', group: 'Brown' },
    '#808000': { name: 'Olive', group: 'Brown' },
    '#8B4513': { name: 'SaddleBrown', group: 'Brown' },
    '#A0522D': { name: 'Sienna', group: 'Brown' },
    '#A52A2A': { name: 'Brown', group: 'Brown' },
    '#800000': { name: 'Maroon', group: 'Brown' },
    '#FFFFFF': { name: 'White', group: 'White' },
    '#FFFAFA': { name: 'Snow', group: 'White' },
    '#F0FFF0': { name: 'HoneyDew', group: 'White' },
    '#F5FFFA': { name: 'MintCream', group: 'White' },
    '#F0FFFF': { name: 'Azure', group: 'White' },
    '#F0F8FF': { name: 'AliceBlue', group: 'White' },
    '#F8F8FF': { name: 'GhostWhite', group: 'White' },
    '#F5F5F5': { name: 'WhiteSmoke', group: 'White' },
    '#FFF5EE': { name: 'SeaShell', group: 'White' },
    '#F5F5DC': { name: 'Beige', group: 'White' },
    '#FDF5E6': { name: 'OldLace', group: 'White' },
    '#FFFAF0': { name: 'FloralWhite', group: 'White' },
    '#FFFFF0': { name: 'Ivory', group: 'White' },
    '#FAEBD7': { name: 'AntiqueWhite', group: 'White' },
    '#FAF0E6': { name: 'Linen', group: 'White' },
    '#FFF0F5': { name: 'LavenderBlush', group: 'White' },
    '#FFE4E1': { name: 'MistyRose', group: 'White' },
    '#DCDCDC': { name: 'Gainsboro', group: 'Gray' },
    '#D3D3D3': { name: 'LightGray', group: 'Gray' },
    '#C0C0C0': { name: 'Silver', group: 'Gray' },
    '#A9A9A9': { name: 'DarkGray', group: 'Gray' },
    '#696969': { name: 'DimGray', group: 'Gray' },
    '#808080': { name: 'Gray', group: 'Gray' },
    '#778899': { name: 'LightSlateGray', group: 'Gray' },
    '#708090': { name: 'SlateGray', group: 'Gray' },
    '#2F4F4F': { name: 'DarkSlateGray', group: 'Gray' },
    '#000000': { name: 'Black', group: 'Gray' },
}

function nearestColor(color: string): ReferenceColor {
    const { r: r1, g: g1, b: b1 } = hexToRGB(color)

    let minDistance = null
    let minColor = null

    for (const referenceColor in referenceColors) {
        const { r: r2, g: g2, b: b2 } = hexToRGB(referenceColor)
        const distance = Math.sqrt((r2 - r1) ** 2 + (g2 - g1) ** 2 + (b2 - b1) ** 2)

        if (minDistance === null || distance < minDistance) {
            minDistance = distance
            minColor = referenceColor
        }
    }

    assert(minColor)

    return referenceColors[minColor]
}

function colorDescription(color: string): string {
    const { name, group } = nearestColor(color)
    const colorName = name.split(/(?=[A-Z])/).join(' ')

    return colorName.includes(group) ? colorName : `${colorName} (${group})`
}
