import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { LoadNext } from '../../DataNode/LoadNext'
import { renderColumn } from '../../DataTable/renderColumn'
import { dataVisualizationLogic } from '../dataVisualizationLogic'

interface TableProps {
    query: DataVisualizationNode
    uniqueKey: string | number | undefined
    context: QueryContext | undefined
    cachedResults: HogQLQueryResponse | undefined
}

export const Table = (props: TableProps): JSX.Element => {
    const { tabularData, tabularColumns, responseLoading, responseError, queryCancelled, response } =
        useValues(dataVisualizationLogic)

    const tableColumns: LemonTableColumn<any[], any>[] = tabularColumns.map(({ column, settings }, index) => ({
        title: settings?.display?.label || column.name,
        render: (_, data, recordIndex: number) => {
            return renderColumn(column.name, data[index], data, recordIndex, {
                kind: NodeKind.DataTableNode,
                source: props.query.source,
            })
        },
    }))

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
