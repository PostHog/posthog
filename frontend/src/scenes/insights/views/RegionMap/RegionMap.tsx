import './RegionMap.scss'

import { useActions, useValues } from 'kea'
import React, { useEffect, useRef } from 'react'
import { ComposableMap, Geographies, Geography } from 'react-simple-maps'

import { gradateColor } from 'lib/utils'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useInsightTooltip } from 'scenes/insights/useInsightTooltip'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartParams, TrendResult } from '~/types'

import { SeriesDatum } from '../../InsightTooltip/insightTooltipUtils'
import { regionMapLogic } from './regionMapLogic'

const SATURATION_FLOOR = 0.2
const REGION_MAP_TOOLTIP_OFFSET_PX = 8
const REGION_MAP_TOPOJSON_URL = `${window.JS_URL || ''}/geo/ne_10m_admin_1_states_provinces.json`

const getSeriesValue = (series: TrendResult | null | undefined): number =>
    series?.aggregated_value ?? series?.count ?? 0

interface RegionProperties {
    subdivisionCode: string
    countryCode: string
    subdivisionName: string
}

const getRegionProperties = (properties: Record<string, unknown>): RegionProperties => ({
    subdivisionCode: (properties['iso_3166_2'] as string) || '',
    countryCode: (properties['iso_a2'] as string) || '',
    subdivisionName: (properties['name'] as string) || '',
})

function useRegionMapTooltip(showPersonsModal: boolean): React.RefObject<HTMLDivElement> {
    const { insightProps } = useValues(insightLogic)
    const logic = regionMapLogic(insightProps)
    const { series, trendsFilter, breakdownFilter, isTooltipShown, currentTooltip, tooltipCoordinates } =
        useValues(logic)
    const { aggregationLabel } = useValues(groupsModel)

    const containerRef = useRef<HTMLDivElement>(null)
    const { getTooltip } = useInsightTooltip()
    const [tooltipRoot, tooltipEl] = getTooltip()
    const groupTypeLabel = aggregationLabel(series?.[0].math_group_type_index).plural

    useEffect(() => {
        tooltipEl.style.opacity = isTooltipShown ? '1' : '0'

        if (!isTooltipShown || !currentTooltip || !tooltipCoordinates) {
            return
        }

        const [subdivisionCode, subdivisionName, countryCode, regionSeries] = currentTooltip
        const aggregatedValue = getSeriesValue(regionSeries)

        tooltipRoot.render(
            <InsightTooltip
                seriesData={[
                    {
                        dataIndex: 1,
                        datasetIndex: 1,
                        id: 1,
                        order: 1,
                        breakdown_value: subdivisionCode,
                        count: aggregatedValue,
                    },
                ]}
                breakdownFilter={breakdownFilter}
                renderSeries={(_: React.ReactNode, datum: SeriesDatum) =>
                    typeof datum.breakdown_value === 'string' && (
                        <div className="flex items-center font-semibold">
                            <span className="text-xl mr-2">{countryCodeToFlag(countryCode)}</span>
                            <span className="whitespace-nowrap">
                                {COUNTRY_CODE_TO_LONG_NAME[countryCode] || countryCode} - {subdivisionName}
                            </span>
                        </div>
                    )
                }
                renderCount={(value: number) => <>{formatAggregationAxisValue(trendsFilter, value)}</>}
                showHeader={false}
                hideColorCol
                hideInspectActorsSection={!showPersonsModal || aggregatedValue === 0}
                groupTypeLabel={groupTypeLabel}
            />
        )
    }, [
        isTooltipShown,
        tooltipCoordinates,
        currentTooltip,
        breakdownFilter,
        trendsFilter,
        showPersonsModal,
        tooltipRoot,
        tooltipEl,
        groupTypeLabel,
    ])

    useEffect(() => {
        if (!isTooltipShown || !tooltipCoordinates || !currentTooltip) {
            tooltipEl.style.left = 'revert'
            tooltipEl.style.top = 'revert'
            return
        }

        const containerRect = containerRef.current?.getBoundingClientRect()
        const tooltipRect = tooltipEl.getBoundingClientRect()
        const [tooltipX, tooltipY] = tooltipCoordinates
        const shouldFlip =
            containerRect &&
            tooltipX + tooltipRect.width + REGION_MAP_TOOLTIP_OFFSET_PX > containerRect.x + containerRect.width
        const xOffset = shouldFlip ? -(tooltipRect.width + REGION_MAP_TOOLTIP_OFFSET_PX) : REGION_MAP_TOOLTIP_OFFSET_PX

        tooltipEl.style.left = `${window.pageXOffset + tooltipX + xOffset}px`
        tooltipEl.style.top = `${window.pageYOffset + tooltipY + REGION_MAP_TOOLTIP_OFFSET_PX}px`
    }, [isTooltipShown, tooltipCoordinates, currentTooltip, tooltipEl])

    return containerRef
}

interface RegionMapContentProps extends ChartParams {
    subdivisionCodeToSeries: Record<string, TrendResult>
    maxAggregatedValue: number
    showTooltip: (regionCode: string, regionName: string, countryCode: string, regionSeries: TrendResult | null) => void
    hideTooltip: () => void
    updateTooltipCoordinates: (x: number, y: number) => void
    onDataPointClick?: QueryContext['onDataPointClick']
    querySource: ReturnType<typeof regionMapLogic>['values']['querySource']
    backgroundColor: string
}

const RegionMapContent = React.memo(
    React.forwardRef<HTMLDivElement, RegionMapContentProps>(
        (
            {
                showPersonsModal,
                subdivisionCodeToSeries,
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
                <div ref={ref} className="RegionMap">
                    <ComposableMap
                        projectionConfig={{
                            scale: 170,
                            center: [0, 0],
                        }}
                        viewBox="0 50 800 450"
                    >
                        <Geographies geography={REGION_MAP_TOPOJSON_URL}>
                            {({ geographies }) =>
                                geographies
                                    .map((geo) => ({
                                        geo,
                                        properties: getRegionProperties(geo.properties as Record<string, unknown>),
                                    }))
                                    .filter(({ properties }) => properties.countryCode !== 'AQ')
                                    .map(({ geo, properties }) => {
                                        const subdivisionCode = properties.subdivisionCode
                                        const subdivisionName = properties.subdivisionName
                                        const countryCode = properties.countryCode
                                        const regionSeries = subdivisionCodeToSeries[subdivisionCode]
                                        const aggregatedValue = getSeriesValue(regionSeries)
                                        const hasValue = aggregatedValue > 0
                                        const normalizedValue =
                                            maxAggregatedValue > 0 ? aggregatedValue / maxAggregatedValue : 0
                                        const fill = hasValue
                                            ? gradateColor(backgroundColor, normalizedValue, SATURATION_FLOOR)
                                            : 'var(--color-border-primary)'

                                        const onClick: React.MouseEventHandler<SVGPathElement> | undefined =
                                            onDataPointClick
                                                ? () => {
                                                      onDataPointClick(
                                                          { breakdown: subdivisionCode.replace('-', '::') },
                                                          regionSeries
                                                      )
                                                      hideTooltip()
                                                  }
                                                : showPersonsModal && regionSeries
                                                  ? () => {
                                                        openPersonsModal({
                                                            title: regionSeries.label,
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
                                                  : undefined

                                        return (
                                            <Geography
                                                key={geo.rsmKey}
                                                geography={geo}
                                                fill={fill}
                                                className="RegionMap__geography"
                                                onMouseEnter={() =>
                                                    showTooltip(
                                                        subdivisionCode,
                                                        subdivisionName,
                                                        countryCode,
                                                        regionSeries ?? null
                                                    )
                                                }
                                                onMouseLeave={hideTooltip}
                                                onMouseMove={(e) => updateTooltipCoordinates(e.clientX, e.clientY)}
                                                onClick={onClick}
                                            />
                                        )
                                    })
                            }
                        </Geographies>
                    </ComposableMap>
                </div>
            )
        }
    )
)

export function RegionMap({ showPersonsModal = true, context }: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = regionMapLogic(insightProps)
    const { subdivisionCodeToSeries, maxAggregatedValue, querySource, theme } = useValues(logic)
    const { showTooltip, hideTooltip, updateTooltipCoordinates } = useActions(logic)

    const containerRef = useRegionMapTooltip(showPersonsModal)

    const backgroundColor = theme?.['preset-1'] ?? '#000000'

    return (
        <RegionMapContent
            showPersonsModal={showPersonsModal}
            subdivisionCodeToSeries={subdivisionCodeToSeries}
            maxAggregatedValue={maxAggregatedValue}
            showTooltip={showTooltip}
            hideTooltip={hideTooltip}
            updateTooltipCoordinates={updateTooltipCoordinates}
            ref={containerRef}
            onDataPointClick={context?.onDataPointClick}
            querySource={querySource}
            backgroundColor={backgroundColor}
        />
    )
}
