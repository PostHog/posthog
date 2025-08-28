import { useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { execHog } from 'lib/hog'
import { lightenDarkenColor } from 'lib/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { renderColumnMeta } from '../../DataTable/renderColumnMeta'
import { TableDataCell, convertTableValue, dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableProps {
    query: DataVisualizationNode
    uniqueKey: string | number | undefined
    context: QueryContext<DataVisualizationNode> | undefined
    cachedResults: HogQLQueryResponse | undefined
    embedded?: boolean
}

export const DEFAULT_PAGE_SIZE = 500

export const Table = (props: TableProps): JSX.Element => {
    const { isDarkModeOn } = useValues(themeLogic)

    const {
        tabularData,
        tabularColumns,
        conditionalFormattingRules,
        responseLoading,
        responseError,
        queryCancelled,
        response,
    } = useValues(dataVisualizationLogic)

    const tableColumns: LemonTableColumn<TableDataCell<any>[], any>[] = tabularColumns.map(
        ({ column, settings }, index) => {
            const { title, ...columnMeta } = renderColumnMeta(column.name, props.query, props.context)

            return {
                ...columnMeta,
                title: settings?.display?.label || title || column.name,
                render: (_, data, recordIndex: number, rowCount: number) => {
                    return renderColumn(column.name, data[index].formattedValue, data, recordIndex, rowCount, {
                        kind: NodeKind.DataTableNode,
                        source: props.query.source,
                    })
                },
                style: (_, data) => {
                    const cf = conditionalFormattingRules
                        .filter((n) => n.columnName === column.name)
                        .filter((n) => {
                            const isValidHog = !!n.bytecode && n.bytecode.length > 0 && n.bytecode[0] === '_H'
                            if (!isValidHog) {
                                posthog.captureException(new Error('Invalid hog bytecode for conditional formatting'), {
                                    formatRule: n,
                                })
                            }

                            return isValidHog
                        })
                        .map((n) => {
                            const res = execHog(n.bytecode, {
                                globals: {
                                    value: data[index].value,
                                    input: convertTableValue(n.input, column.type.name),
                                },
                                functions: {},
                                maxAsyncSteps: 0,
                            })

                            return {
                                rule: n,
                                result: res.result,
                            }
                        })

                    const conditionalFormattingMatches = cf.find((n) => Boolean(n.result))

                    if (conditionalFormattingMatches) {
                        const ruleColor = conditionalFormattingMatches.rule.color
                        const colorMode = conditionalFormattingMatches.rule.colorMode ?? 'light'

                        // If the color mode matches the current theme, return as it was saved
                        if ((colorMode === 'dark' && isDarkModeOn) || (colorMode === 'light' && !isDarkModeOn)) {
                            return {
                                backgroundColor: ruleColor,
                            }
                        }

                        // If the color mode is dark, but we're in light mode - then lighten the color
                        if (colorMode === 'dark' && !isDarkModeOn) {
                            return {
                                backgroundColor: lightenDarkenColor(ruleColor, 30),
                            }
                        }

                        // If the color mode is light, but we're in dark mode - then darken the color
                        return {
                            backgroundColor: lightenDarkenColor(ruleColor, -30),
                        }
                    }

                    return undefined
                },
            }
        }
    )

    return (
        <LemonTable
            dataSource={tabularData}
            columns={tableColumns}
            loading={responseLoading}
            pagination={{ pageSize: DEFAULT_PAGE_SIZE }}
            emptyState={
                responseError ? (
                    <InsightErrorState
                        query={props.query}
                        excludeDetail
                        title={
                            queryCancelled
                                ? 'The query was cancelled'
                                : response && 'error' in response
                                  ? (response as any).error
                                  : responseError
                        }
                    />
                ) : (
                    <InsightEmptyState heading="There are no matching rows for this query" detail="" />
                )
            }
            footer={tabularData.length > 0 ? <LoadNext query={props.query} /> : null}
            rowClassName="DataVizRow"
            embedded={props.embedded}
        />
    )
}
