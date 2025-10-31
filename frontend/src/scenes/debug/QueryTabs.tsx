import { useState } from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { Query } from '~/queries/Query/Query'
import { Timings } from '~/queries/nodes/DataNode/ElapsedTime'
import { HogQLMetadataResponse, InsightVizNode, Node, NodeKind, QueryTiming } from '~/queries/schema/schema-general'
import { isDataTableNode, isInsightQueryNode, isInsightVizNode } from '~/queries/utils'

import { QueryLogTable } from './QueryLogTable'

function toLineColumn(hogql: string, position: number): { line: number; column: number } {
    const lines = hogql.split('\n')
    let line = 0
    let column = 0
    for (let i = 0; i < lines.length; i++) {
        if (position < lines[i].length) {
            line = i + 1
            column = position + 1
            break
        }
        position -= lines[i].length + 1
    }
    return { line, column }
}

function toLine(hogql: string, position: number): number {
    return toLineColumn(hogql, position).line
}

function toColumn(hogql: string, position: number): number {
    return toLineColumn(hogql, position).column
}
interface QueryTabsProps<Q extends Node> {
    query: Q
    queryKey: `new-${string}`
    response?: Q['response'] | null
    setQuery: (query: Q) => void
    onLoadQuery?: (query: string) => void
}
export function QueryTabs<Q extends Node>({
    query,
    queryKey,
    setQuery,
    response,
    onLoadQuery,
}: QueryTabsProps<Q>): JSX.Element {
    const [tab, setTab] = useState<string | null>(null)
    const clickHouseTime = (response?.timings as QueryTiming[])?.find(({ k }) => k === './clickhouse_execute')?.t ?? 0
    const explainTime = (response?.timings as QueryTiming[])?.find(({ k }) => k === './explain')?.t ?? 0
    const totalTime = (response?.timings as QueryTiming[])?.find(({ k }) => k === '.')?.t ?? 0
    const hogQLTime = totalTime - explainTime - clickHouseTime
    const tabs: LemonTabsProps<string>['tabs'] = query
        ? [
              response?.error && {
                  key: 'error',
                  label: 'Error',
                  content: (
                      <>
                          <h2 className="text-danger">Error Running Query!</h2>
                          <CodeSnippet language={Language.Text} wrap>
                              {response.error}
                          </CodeSnippet>
                      </>
                  ),
              },
              isInsightVizNode(query) && {
                  key: 'viz',
                  label: 'Visualization',
                  content: (
                      <Query
                          uniqueKey={queryKey}
                          query={query}
                          setQuery={(query) => setQuery(query)}
                          context={{
                              insightProps: {
                                  dashboardItemId: queryKey,
                                  query,
                                  setQuery: (query) => setQuery(query),
                                  dataNodeCollectionId: queryKey,
                              },
                          }}
                      />
                  ),
              },
              isInsightQueryNode(query) && {
                  key: 'insight',
                  label: 'Insight',
                  content: (
                      <Query
                          uniqueKey={queryKey}
                          query={{ kind: NodeKind.InsightVizNode, source: query, full: true } as InsightVizNode}
                          // @ts-expect-error - TS is wary of `setQuery` being different later, but we're OK
                          setQuery={(query) => setQuery(query)}
                      />
                  ),
              },
              isDataTableNode(query) && {
                  key: 'table',
                  label: 'Data Table',
                  content: <Query uniqueKey={queryKey} query={query} setQuery={(query) => setQuery(query)} />,
              },

              (response?.result || response?.results) && {
                  key: 'result',
                  label: 'Result JSON',
                  content: (
                      <CodeEditor
                          className="border"
                          language="json"
                          value={JSON.stringify(response?.result || response?.results, null, 2)}
                          height={500}
                          path={`debug/${queryKey}/result.json`}
                      />
                  ),
              },
              response?.hogql && {
                  key: 'hogql',
                  label: (
                      <>
                          SQL
                          {hogQLTime && <LemonTag className="ml-2">{Math.floor(hogQLTime * 10) / 10}s</LemonTag>}
                      </>
                  ),
                  content: (
                      <CodeEditor
                          className="border"
                          language="sql"
                          value={String(response.hogql)}
                          height={500}
                          path={`debug/${queryKey}/hogql.sql`}
                      />
                  ),
              },
              response?.clickhouse && {
                  key: 'clickhouse',
                  label: (
                      <>
                          Clickhouse
                          {clickHouseTime && (
                              <LemonTag className="ml-2">{Math.floor(clickHouseTime * 10) / 10}s</LemonTag>
                          )}
                      </>
                  ),
                  content: (
                      <CodeEditor
                          className="border"
                          language="sql"
                          value={String(response.clickhouse)}
                          height={500}
                          path={`debug/${queryKey}/hogql.sql`}
                      />
                  ),
              },
              response?.explain && {
                  key: 'explain',
                  label: 'Explain',
                  content: <CodeSnippet wrap>{response.explain.join('\n')}</CodeSnippet>,
              },
              response?.timings && {
                  key: 'timings',
                  label: 'Timings',
                  content: <Timings timings={response?.timings} elapsedTime={response?.elapsedTime} />,
              },
              response && {
                  key: 'response',
                  label: 'Full response',
                  content: (
                      <CodeEditor
                          className="border"
                          language="json"
                          value={JSON.stringify(response, null, 2)}
                          height={500}
                          path={`debug/${queryKey}/response.json`}
                      />
                  ),
              },
              response?.metadata && {
                  key: 'metadata',
                  label: 'Metadata',
                  content: (
                      <LemonTable
                          dataSource={[
                              ...(response.metadata as HogQLMetadataResponse).errors.map((error) => ({
                                  type: 'error',
                                  line: toLine(response.hogql ?? '', error.start ?? 0),
                                  column: toColumn(response.hogql ?? '', error.start ?? 0),
                                  ...error,
                              })),
                              ...(response.metadata as HogQLMetadataResponse).warnings.map((warn) => ({
                                  type: 'warning',
                                  line: toLine(response.hogql ?? '', warn.start ?? 0),
                                  column: toColumn(response.hogql ?? '', warn.start ?? 0),
                                  ...warn,
                              })),
                              ...(response.metadata as HogQLMetadataResponse).notices.map((notice) => ({
                                  type: 'notice',
                                  line: toLine(response.hogql ?? '', notice.start ?? 0),
                                  column: toColumn(response.hogql ?? '', notice.start ?? 0),
                                  ...notice,
                              })),
                          ].sort((a, b) => (a.start ?? 0) - (b.start ?? 0))}
                          columns={[
                              { title: 'Line', dataIndex: 'line', key: 'line', width: '40px' },
                              { title: 'Column', dataIndex: 'column', key: 'column', width: '40px' },
                              { title: 'Type', dataIndex: 'type', key: 'type', width: '80px' },
                              { title: 'Message', dataIndex: 'message', key: 'message' },
                          ]}
                      />
                  ),
              },
              onLoadQuery && {
                  key: 'query_log',
                  label: 'Query log',
                  content: <QueryLogTable queryKey={queryKey} onLoadQuery={onLoadQuery} />,
              },
          ]
              .filter(Boolean)
              .map((tab) => ({ ...tab, content: <ErrorBoundary>{tab.content}</ErrorBoundary> }))
        : []

    return (
        <ErrorBoundary>
            <LemonTabs
                activeKey={tab && tabs.find((t) => t && t.key === tab) ? tab : (tabs[0] && tabs[0].key) || 'response'}
                onChange={(t) => setTab(t)}
                tabs={tabs}
            />
        </ErrorBoundary>
    )
}
