import './WorldMap.scss'

import { useActions, useValues } from 'kea'
import { BRAND_BLUE_HSL, gradateColor } from 'lib/colors'
import React, { HTMLProps, useEffect, useRef } from 'react'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { groupsModel } from '~/models/groupsModel'
import { InsightQueryNode, NodeKind } from '~/queries/schema'
import { ChartDisplayType, ChartParams, TrendResult } from '~/types'

import { SeriesDatum } from '../../InsightTooltip/insightTooltipUtils'
import { ensureTooltip } from '../LineGraph/LineGraph'
import { countryCodeToFlag, countryCodeToName } from './countryCodes'
import { countryVectors } from './countryVectors'
import { worldMapLogic } from './worldMapLogic'

/** The saturation of a country is proportional to its value BUT the saturation has a floor to improve visibility. */
const SATURATION_FLOOR = 0.2
/** The tooltip is offset by a few pixels from the cursor to give it some breathing room. */
const WORLD_MAP_TOOLTIP_OFFSET_PX = 8

function useWorldMapTooltip(showPersonsModal: boolean): React.RefObject<SVGSVGElement> {
    const { insightProps } = useValues(insightLogic)
    const { series, trendsFilter, breakdownFilter, isTooltipShown, currentTooltip, tooltipCoordinates } = useValues(
        worldMapLogic(insightProps)
    )
    const { aggregationLabel } = useValues(groupsModel)

    const svgRef = useRef<SVGSVGElement>(null)

    const svgRect = svgRef.current?.getBoundingClientRect()
    const [tooltipRoot, tooltipEl] = ensureTooltip()

    useEffect(() => {
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'

        if (tooltipCoordinates) {
            tooltipRoot.render(
                <>
                    {currentTooltip && (
                        <InsightTooltip
                            seriesData={[
                                {
                                    dataIndex: 1,
                                    datasetIndex: 1,
                                    id: 1,
                                    breakdown_value: currentTooltip[0],
                                    count: currentTooltip[1]?.aggregated_value || 0,
                                },
                            ]}
                            breakdownFilter={breakdownFilter}
                            renderSeries={(_: React.ReactNode, datum: SeriesDatum) =>
                                typeof datum.breakdown_value === 'string' && (
                                    <div className="flex items-center font-semibold">
                                        <span className="text-xl mr-2">{countryCodeToFlag(datum.breakdown_value)}</span>
                                        <span className="whitespace-nowrap">
                                            {countryCodeToName[datum.breakdown_value]}
                                        </span>
                                    </div>
                                )
                            }
                            renderCount={(value: number) => <>{formatAggregationAxisValue(trendsFilter, value)}</>}
                            showHeader={false}
                            hideColorCol
                            hideInspectActorsSection={!showPersonsModal || !currentTooltip[1]}
                            groupTypeLabel={aggregationLabel(series?.[0].math_group_type_index).plural}
                        />
                    )}
                </>
            )
        } else {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
        }
    }, [isTooltipShown, tooltipCoordinates, currentTooltip])

    useEffect(() => {
        if (tooltipCoordinates) {
            const tooltipRect = tooltipEl.getBoundingClientRect()
            // Put the tooltip to the bottom right of the cursor, but flip to left if tooltip doesn't fit
            let xOffset: number
            if (
                svgRect &&
                tooltipRect &&
                tooltipCoordinates[0] + tooltipRect.width + WORLD_MAP_TOOLTIP_OFFSET_PX > svgRect.x + svgRect.width
            ) {
                xOffset = -(tooltipRect.width + WORLD_MAP_TOOLTIP_OFFSET_PX)
            } else {
                xOffset = WORLD_MAP_TOOLTIP_OFFSET_PX
            }
            tooltipEl.style.left = `${window.pageXOffset + tooltipCoordinates[0] + xOffset}px`
            tooltipEl.style.top = `${window.pageYOffset + tooltipCoordinates[1] + WORLD_MAP_TOOLTIP_OFFSET_PX}px`
        }
    }, [currentTooltip, tooltipEl])

    return svgRef
}

interface WorldMapSVGProps extends ChartParams {
    countryCodeToSeries: Record<string, TrendResult>
    maxAggregatedValue: number
    showTooltip: (countryCode: string, countrySeries: TrendResult | null) => void
    hideTooltip: () => void
    updateTooltipCoordinates: (x: number, y: number) => void
    worldMapCountryProps?: (
        countryCode: string,
        countrySeries: TrendResult | undefined
    ) => Omit<HTMLProps<SVGElement>, 'key'>
    querySource: InsightQueryNode | null
}

const WorldMapSVG = React.memo(
    React.forwardRef<SVGSVGElement, WorldMapSVGProps>(
        (
            {
                showPersonsModal,
                countryCodeToSeries,
                maxAggregatedValue,
                showTooltip,
                hideTooltip,
                updateTooltipCoordinates,
                worldMapCountryProps,
                querySource,
            },
            ref
        ) => {
            return (
                <svg
                    className="WorldMap"
                    xmlns="http://www.w3.org/2000/svg"
                    version="1.1"
                    viewBox="0 0 2754 1200"
                    width="100%"
                    height="100%"
                    id="svg"
                    ref={ref}
                >
                    {Object.entries(countryVectors).map(([countryCode, countryElement]) => {
                        if (countryCode.length !== 2) {
                            return null // Avoid this issue: https://github.com/storybookjs/storybook/issues/9832
                        }
                        const countrySeries: TrendResult | undefined = countryCodeToSeries[countryCode]
                        const aggregatedValue = countrySeries?.aggregated_value || 0
                        const fill = aggregatedValue
                            ? gradateColor(BRAND_BLUE_HSL, aggregatedValue / maxAggregatedValue, SATURATION_FLOOR)
                            : undefined

                        const {
                            onClick: propsOnClick,
                            style,
                            ...props
                        } = worldMapCountryProps
                            ? worldMapCountryProps(countryCode, countrySeries)
                            : { onClick: undefined, style: undefined }

                        let onClick: typeof propsOnClick
                        if (propsOnClick) {
                            onClick = (e) => {
                                propsOnClick(e)
                                hideTooltip()
                            }
                        } else if (showPersonsModal && countrySeries) {
                            onClick = () => {
                                if (showPersonsModal && countrySeries) {
                                    openPersonsModal({
                                        title: countrySeries.label,
                                        query: {
                                            kind: NodeKind.InsightActorsQuery,
                                            source: querySource!,
                                            includeRecordings: true,
                                        },
                                        additionalSelect: {
                                            value_at_data_point: 'event_count',
                                            matched_recordings: 'matched_recordings',
                                        },
                                        orderBy: ['event_count DESC, actor_id DESC'],
                                    })
                                }
                            }
                        }

                        return React.cloneElement(countryElement, {
                            key: countryCode,
                            style: { color: fill, cursor: onClick ? 'pointer' : undefined, ...style },
                            onMouseEnter: () => showTooltip(countryCode, countrySeries || null),
                            onMouseLeave: () => hideTooltip(),
                            onMouseMove: (e: MouseEvent) => {
                                updateTooltipCoordinates(e.clientX, e.clientY)
                            },
                            onClick,
                            ...props,
                        })
                    })}
                </svg>
            )
        }
    )
)

export function WorldMap({ showPersonsModal = true, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { countryCodeToSeries, maxAggregatedValue, querySource } = useValues(worldMapLogic(insightProps))
    const { showTooltip, hideTooltip, updateTooltipCoordinates } = useActions(worldMapLogic(insightProps))
    const renderingMetadata = context?.chartRenderingMetadata?.[ChartDisplayType.WorldMap]

    const svgRef = useWorldMapTooltip(showPersonsModal)

    return (
        <WorldMapSVG
            showPersonsModal={showPersonsModal}
            countryCodeToSeries={countryCodeToSeries}
            maxAggregatedValue={maxAggregatedValue}
            showTooltip={showTooltip}
            hideTooltip={hideTooltip}
            updateTooltipCoordinates={updateTooltipCoordinates}
            ref={svgRef}
            worldMapCountryProps={renderingMetadata?.countryProps}
            querySource={querySource}
        />
    )
}
