import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { execHog } from 'lib/hog'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { convertTableValue, dataVisualizationLogic, TableDataCell } from '../dataVisualizationLogic'

interface TableProps {
    query: DataVisualizationNode
    uniqueKey: string | number | undefined
    context: QueryContext<DataVisualizationNode> | undefined
    cachedResults: HogQLQueryResponse | undefined
}

export const Table = (props: TableProps): JSX.Element => {
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
        ({ column, settings }, index) => ({
            title: settings?.display?.label || column.name,
            render: (_, data, recordIndex: number) => {
                return renderColumn(column.name, data[index].formattedValue, data, recordIndex, {
                    kind: NodeKind.DataTableNode,
                    source: props.query.source,
                })
            },
            style: (_, data) => {
                const cf = conditionalFormattingRules
                    .filter((n) => n.columnName === column.name)
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
                    return {
                        backgroundColor: conditionalFormattingMatches.rule.color,
                    }
                }

                return undefined
            },
        })
    )

    return (
        <div className="relative w-full flex flex-col gap-4 flex-1 h-full">
            <LemonTable
                dataSource={tabularData}
                columns={tableColumns}
                loading={responseLoading}
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
                        <InsightEmptyState
                            heading={props.context?.emptyStateHeading}
                            detail={props.context?.emptyStateDetail}
                        />
                    )
                }
                footer={tabularData.length > 0 ? <LoadNext query={props.query} /> : null}
                rowClassName="DataVizRow"
            />
        </div>
    )
}
