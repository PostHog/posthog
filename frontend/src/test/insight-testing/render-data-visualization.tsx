import { render } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import { AnyResponseType, DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType } from '~/types'

import { initKeaTests } from '../init'

export const DATA_VIZ_TEST_KEY = 'sql-test-harness'

/** Minimal `[columnName, clickhouseType]` + row-major results — the same shape the
 *  `/query` endpoint returns, distilled to what the chart selectors read. */
export interface DataVizFixture {
    columns: string[]
    types: [string, string][]
    results: unknown[][]
}

export function buildHogQLResponse({ columns, types, results }: DataVizFixture): HogQLQueryResponse {
    return {
        results,
        columns,
        types,
        hogql: '',
        hasMore: false,
    } as HogQLQueryResponse
}

export function buildDataVisualizationQuery(overrides?: Partial<DataVisualizationNode>): DataVisualizationNode {
    return {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT month, pageviews FROM events GROUP BY month ORDER BY month',
        },
        display: ChartDisplayType.ActionsLineGraph,
        ...overrides,
    }
}

function isFixture(response: DataVizFixture | AnyResponseType): response is DataVizFixture {
    return Array.isArray((response as DataVizFixture).types)
}

export interface RenderDataVisualizationProps {
    query?: DataVisualizationNode
    /** Row-major fixture or a pre-built HogQL response, fed in via `cachedResults` to skip the network. */
    response: DataVizFixture | AnyResponseType
    /** Defaults to `{ 'product-analytics-quill-sql-charts': true }`; merge in more or override. */
    featureFlags?: Record<string, string | boolean>
    readOnly?: boolean
    embedded?: boolean
    context?: QueryContext<DataVisualizationNode>
}

/** Mount a SQL insight (`DataVisualizationNode`) the way the real scene does — through
 *  `DataTableVisualization` → `dataVisualizationLogic` → `LineGraph` → the flag-gated quill
 *  chart — with the query result injected via `cachedResults` so nothing hits the network. */
export function renderDataVisualization(props: RenderDataVisualizationProps): ReturnType<typeof render> {
    const featureFlags = { [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS]: true, ...props.featureFlags }

    initKeaTests()
    actionsModel.mount()
    groupsModel.mount()

    const ffLogic = featureFlagLogic()
    ffLogic.mount()
    ffLogic.actions.setFeatureFlags(Object.keys(featureFlags), featureFlags)

    const cachedResults = isFixture(props.response) ? buildHogQLResponse(props.response) : props.response

    return render(
        <DataTableVisualization
            uniqueKey={DATA_VIZ_TEST_KEY}
            query={props.query ?? buildDataVisualizationQuery()}
            setQuery={() => {}}
            cachedResults={cachedResults}
            context={props.context}
            readOnly={props.readOnly ?? true}
            embedded={props.embedded}
        />
    )
}
