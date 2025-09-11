import './WorldMap.scss'

import { style } from 'd3'
import { props, useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'

import { gradateColor } from 'lib/utils'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { groupsModel } from '~/models/groupsModel'
import { InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartParams, TrendResult } from '~/types'

import { SeriesDatum } from '../../InsightTooltip/insightTooltipUtils'
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
    const { getTooltip } = useInsightTooltip()
    const [tooltipRoot, tooltipEl] = getTooltip()

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
                                    order: 1,
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
                                            {COUNTRY_CODE_TO_LONG_NAME[datum.breakdown_value]}
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
    }, [isTooltipShown, tooltipCoordinates, currentTooltip]) // oxlint-disable-line react-hooks/exhaustive-deps

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
    }, [currentTooltip, tooltipEl]) // oxlint-disable-line react-hooks/exhaustive-deps

    return svgRef
}

interface WorldMapSVGProps extends ChartParams {
    countryCodeToSeries: Record<string, TrendResult>
    maxAggregatedValue: number
    showTooltip: (countryCode: string, countrySeries: TrendResult | null) => void
    hideTooltip: () => void
    updateTooltipCoordinates: (x: number, y: number) => void
    onDataPointClick?: QueryContext['onDataPointClick']
    querySource: InsightQueryNode | null
    backgroundColor: string
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
                onDataPointClick,
                querySource,
                backgroundColor,
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
                            ? gradateColor(backgroundColor, aggregatedValue / maxAggregatedValue, SATURATION_FLOOR)
                            : undefined

                        let onClick: React.MouseEventHandler<SVGPathElement> | undefined
                        if (onDataPointClick) {
                            onClick = () => {
                                onDataPointClick(
                                    {
                                        breakdown: countryCode,
                                    },
                                    countrySeries
                                )
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
                            style: {
                                color: fill,
                                '--world-map-hover': backgroundColor,
                                cursor: onClick ? 'pointer' : undefined,
                                ...style,
                            },
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
    const { countryCodeToSeries, maxAggregatedValue, querySource, theme } = useValues(worldMapLogic(insightProps))
    const { showTooltip, hideTooltip, updateTooltipCoordinates } = useActions(worldMapLogic(insightProps))

    const svgRef = useWorldMapTooltip(showPersonsModal)

    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found

    return (
        <WorldMapSVG
            showPersonsModal={showPersonsModal}
            countryCodeToSeries={countryCodeToSeries}
            maxAggregatedValue={maxAggregatedValue}
            showTooltip={showTooltip}
            hideTooltip={hideTooltip}
            updateTooltipCoordinates={updateTooltipCoordinates}
            ref={svgRef}
            onDataPointClick={context?.onDataPointClick}
            querySource={querySource}
            backgroundColor={backgroundColor}
        />
    )
}
