import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { ChartFilter } from 'lib/components/ChartFilter/ChartFilter'
import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { RetentionChartPicker } from 'scenes/insights/filters/RetentionChartPicker'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isDisplayTabSupported } from '~/queries/nodes/DataVisualization/Components/SideBar'
import { DataVisualizationNode, HogQLVariable, Node } from '~/queries/schema/schema-general'
import {
    isDataVisualizationNodeWithHogQLQuery,
    isInsightVizNode,
    isRetentionQuery,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { ChartDisplayType, InsightType, RetentionDashboardDisplayType } from '~/types'

import { DashboardSqlChartType, DashboardSqlDisplayOptions } from './DashboardSqlDisplayOptions'

export interface DashboardVisualizationPersistence {
    saving: 'chart-type' | 'display-options' | null
    version: number
    persistChartType: (display: ChartDisplayType) => void
    persistDisplayOptions: (query: DataVisualizationNode) => void
}

type ProductAnalyticsChartPicker = 'chart-filter' | 'retention'

function productAnalyticsChartPicker(query: Node | null, canPersist: boolean): ProductAnalyticsChartPicker | null {
    if (!canPersist || !isInsightVizNode(query)) {
        return null
    }
    if (isTrendsQuery(query.source) || isStickinessQuery(query.source)) {
        return 'chart-filter'
    }
    if (isRetentionQuery(query.source)) {
        return query.vizSpecificOptions?.[InsightType.RETENTION]?.hideLineGraph ? null : 'retention'
    }
    return null
}

function DashboardRetentionChartPicker({ disabledReason }: { disabledReason?: string }): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const selectChart = useCallback(
        (display: ChartDisplayType): void => {
            updateInsightFilter({
                display,
                ...(!retentionFilter?.dashboardDisplay ||
                retentionFilter.dashboardDisplay === RetentionDashboardDisplayType.TableOnly
                    ? { dashboardDisplay: RetentionDashboardDisplayType.GraphOnly }
                    : {}),
            })
        },
        [retentionFilter?.dashboardDisplay, updateInsightFilter]
    )

    return <RetentionChartPicker fullWidth disabledReason={disabledReason} onSelect={selectChart} />
}

export function sqlQueryForVisualizationPicker(query: Node | null, canPersist: boolean): DataVisualizationNode | null {
    return canPersist && query && isDataVisualizationNodeWithHogQLQuery(query) ? query : null
}

export function useDashboardVisualizationOptions({
    query,
    insightData,
    variablesOverride,
    loading,
    persistence,
    savingDisplayOptions,
}: {
    query: Node | null
    insightData: Record<string, any>
    variablesOverride?: Record<string, HogQLVariable> | null
    loading?: boolean
    persistence?: DashboardVisualizationPersistence
    savingDisplayOptions?: boolean
}): LemonMenuItems {
    const sqlQuery = sqlQueryForVisualizationPicker(query, !!persistence)
    const insightChartPicker = productAnalyticsChartPicker(query, !!persistence)
    const overriddenVariable = Object.keys(sqlQuery?.source.variables ?? {}).find((key) => variablesOverride?.[key])

    const pickerProps = {
        query: sqlQuery,
        cachedResults: insightData,
        variablesOverride,
        loading,
        saving: persistence?.saving === 'chart-type',
        version: persistence?.version,
        overriddenVariable,
        persistChartType: persistence?.persistChartType,
    }
    const pickerPropsRef = useRef(pickerProps)
    pickerPropsRef.current = pickerProps
    const renderPicker = useCallback((): JSX.Element => {
        const props = pickerPropsRef.current
        return (
            <DashboardSqlChartType
                key={props.version}
                query={props.query!}
                cachedResults={props.cachedResults}
                variablesOverride={props.variablesOverride}
                loading={props.loading}
                saving={props.saving}
                disabledReason={
                    props.overriddenVariable
                        ? 'This dashboard overrides a variable this insight uses. Open the insight to change its chart type.'
                        : undefined
                }
                persistChartType={props.persistChartType!}
            />
        )
    }, [])

    const insightChartPickerPropsRef = useRef({ insightChartPicker, savingDisplayOptions })
    insightChartPickerPropsRef.current = { insightChartPicker, savingDisplayOptions }
    const renderInsightChartPicker = useCallback((): JSX.Element => {
        const props = insightChartPickerPropsRef.current
        const disabledReason = props.savingDisplayOptions ? 'Saving…' : undefined
        return (
            <div className="w-full px-2 pb-2">
                {props.insightChartPicker === 'retention' ? (
                    <DashboardRetentionChartPicker disabledReason={disabledReason} />
                ) : (
                    <ChartFilter fullWidth disabledReason={disabledReason} />
                )}
            </div>
        )
    }, [])

    const displayOptionsProps = {
        query: sqlQuery,
        cachedResults: insightData,
        variablesOverride,
        loading,
        persistence,
    }
    const displayOptionsPropsRef = useRef(displayOptionsProps)
    displayOptionsPropsRef.current = displayOptionsProps
    const renderDisplayOptions = useCallback((): JSX.Element => {
        const props = displayOptionsPropsRef.current
        if (props.loading) {
            return (
                <div className="flex min-h-20 w-80 items-center justify-center gap-2 text-muted" role="status">
                    <Spinner /> Loading display options
                </div>
            )
        }
        return (
            <DashboardSqlDisplayOptions
                key={props.persistence!.version}
                query={props.query!}
                cachedResults={props.cachedResults}
                variablesOverride={props.variablesOverride}
                persistDisplayOptions={props.persistence!.persistDisplayOptions}
                disabled={props.persistence!.saving === 'chart-type'}
            />
        )
    }, [])

    return useMemo<LemonMenuItems>(() => {
        if ((!sqlQuery && !insightChartPicker) || !persistence) {
            return []
        }

        return [
            {
                title:
                    insightChartPicker && savingDisplayOptions ? (
                        <h5 className="mx-2 my-1 flex items-center justify-between gap-2">
                            Chart type
                            <span className="flex items-center gap-1 font-normal text-muted" role="status">
                                <Spinner /> Saving
                            </span>
                        </h5>
                    ) : (
                        'Chart type'
                    ),
                items: [{ label: sqlQuery ? renderPicker : renderInsightChartPicker }],
            },
            sqlQuery && isDisplayTabSupported(sqlQuery.display ?? ChartDisplayType.ActionsTable)
                ? {
                      key: 'display',
                      title: (
                          <h5 className="mx-2 my-1 flex items-center justify-between gap-2">
                              Display
                              {persistence.saving ? (
                                  <span className="flex items-center gap-1 font-normal text-muted" role="status">
                                      <Spinner /> Saving
                                  </span>
                              ) : null}
                          </h5>
                      ),
                      items: [{ label: renderDisplayOptions }],
                  }
                : false,
        ]
    }, [
        sqlQuery,
        insightChartPicker,
        persistence,
        savingDisplayOptions,
        renderPicker,
        renderInsightChartPicker,
        renderDisplayOptions,
    ])
}
