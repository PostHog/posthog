import { useValues, useActions } from 'kea'
import React, { useEffect, useRef } from 'react'
import ReactDOM from 'react-dom'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ChartParams, TrendResult } from '~/types'
import './WorldMap.scss'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { SeriesDatum } from '../../InsightTooltip/insightTooltipUtils'
import { ensureTooltipElement } from '../LineGraph/LineGraph'
import { worldMapLogic } from './worldMapLogic'
import { countryCodeToFlag, countryCodeToName } from './countryCodes'
import { personsModalLogic, PersonsModalParams } from 'scenes/trends/personsModalLogic'
import { countryVectors } from './countryVectors'
import { groupsModel } from '~/models/groupsModel'
import { toLocalFilters } from '../../filters/ActionFilter/entityFilterLogic'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

/** The saturation of a country is proportional to its value BUT the saturation has a floor to improve visibility. */
const SATURATION_FLOOR = 0.2
/** --brand-blue in HSL for saturation mixing */
const BRAND_BLUE_HSL: [number, number, number] = [228, 100, 56]
/** The tooltip is offset by a few pixels from the cursor to give it some breathing room. */
const WORLD_MAP_TOOLTIP_OFFSET_PX = 8

function useWorldMapTooltip(showPersonsModal: boolean): React.RefObject<SVGSVGElement> {
    const { insightProps } = useValues(insightLogic)
    const { filters, isTooltipShown, currentTooltip, tooltipCoordinates } = useValues(worldMapLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const svgRef = useRef<SVGSVGElement>(null)

    useEffect(() => {
        const svgRect = svgRef.current?.getBoundingClientRect()
        const tooltipEl = ensureTooltipElement()
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'
        const tooltipRect = tooltipEl.getBoundingClientRect()
        if (tooltipCoordinates) {
            ReactDOM.render(
                <>
                    {currentTooltip && (
                        <InsightTooltip
                            seriesData={[
                                {
                                    dataIndex: 1,
                                    datasetIndex: 1,
                                    id: 1,
                                    filter: {},
                                    breakdown_value: currentTooltip[0],
                                    count: currentTooltip[1]?.aggregated_value || 0,
                                },
                            ]}
                            renderSeries={(_: React.ReactNode, datum: SeriesDatum) =>
                                typeof datum.breakdown_value === 'string' && (
                                    <div className="flex items-center">
                                        <span style={{ fontSize: '1.25rem' }} className="mr-2">
                                            {countryCodeToFlag(datum.breakdown_value)}
                                        </span>
                                        <span style={{ whiteSpace: 'nowrap' }}>
                                            {countryCodeToName[datum.breakdown_value]}
                                        </span>
                                    </div>
                                )
                            }
                            renderCount={(value: number) => (
                                <>{formatAggregationAxisValue(filters.aggregation_axis_format, value)}</>
                            )}
                            showHeader={false}
                            hideColorCol
                            hideInspectActorsSection={!showPersonsModal || !currentTooltip[1]}
                            groupTypeLabel={aggregationLabel(toLocalFilters(filters)[0].math_group_type_index).plural}
                        />
                    )}
                </>,
                tooltipEl
            )
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
        } else {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
        }
    }, [isTooltipShown, tooltipCoordinates, currentTooltip])

    return svgRef
}

interface WorldMapSVGProps extends ChartParams {
    countryCodeToSeries: Record<string, TrendResult>
    maxAggregatedValue: number
    showTooltip: (countryCode: string, countrySeries: TrendResult | null) => void
    hideTooltip: () => void
    updateTooltipCoordinates: (x: number, y: number) => void
    loadPeople: (peopleParams: PersonsModalParams) => void
}

// eslint-disable-next-line react/display-name
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
                loadPeople,
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
                        const saturation =
                            SATURATION_FLOOR + (1 - SATURATION_FLOOR) * (aggregatedValue / maxAggregatedValue)
                        const fill = aggregatedValue
                            ? `hsl(${BRAND_BLUE_HSL[0]} ${BRAND_BLUE_HSL[1]}% ${
                                  100 - (100 - BRAND_BLUE_HSL[2]) * saturation
                              }%)`
                            : undefined
                        return React.cloneElement(countryElement, {
                            key: countryCode,
                            style: { color: fill, cursor: showPersonsModal && countrySeries ? 'pointer' : undefined },
                            onMouseEnter: () => showTooltip(countryCode, countrySeries || null),
                            onMouseLeave: () => hideTooltip(),
                            onMouseMove: (e: MouseEvent) => {
                                updateTooltipCoordinates(e.clientX, e.clientY)
                            },
                            onClick: () => {
                                if (showPersonsModal && countrySeries) {
                                    loadPeople({
                                        action: countrySeries.action,
                                        label: countryCodeToName[countrySeries.breakdown_value as string],
                                        date_from: countrySeries.filter?.date_from as string,
                                        date_to: countrySeries.filter?.date_to as string,
                                        filters: countrySeries.filter || {},
                                        breakdown_value: countrySeries.breakdown_value,
                                        saveOriginal: true,
                                        pointValue: countrySeries.aggregated_value,
                                    })
                                }
                            },
                        })
                    })}
                </svg>
            )
        }
    )
)

export function WorldMap({ showPersonsModal = true }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const localLogic = worldMapLogic(insightProps)
    const { countryCodeToSeries, maxAggregatedValue } = useValues(localLogic)
    const { showTooltip, hideTooltip, updateTooltipCoordinates } = useActions(localLogic)
    const { loadPeople } = useActions(personsModalLogic)

    const svgRef = useWorldMapTooltip(showPersonsModal)

    return (
        <WorldMapSVG
            showPersonsModal={showPersonsModal}
            countryCodeToSeries={countryCodeToSeries}
            maxAggregatedValue={maxAggregatedValue}
            showTooltip={showTooltip}
            hideTooltip={hideTooltip}
            updateTooltipCoordinates={updateTooltipCoordinates}
            loadPeople={loadPeople}
            ref={svgRef}
        />
    )
}
