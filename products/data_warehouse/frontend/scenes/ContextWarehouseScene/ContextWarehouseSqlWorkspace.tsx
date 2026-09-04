import { IconPlay } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCard, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { ContextWarehouseAiPanel } from './ContextWarehouseAiPanel'

type QueryResult = {
    billingInterval: string
    revenue: string
    change: string
}

type ContextWarehouseSqlWorkspaceProps = {
    query: string
    results: QueryResult[]
    composerValue: string
    onQueryChange: (query: string) => void
    onRun: () => void
    onComposerChange: (value: string) => void
    onComposerSubmit: () => void
}

export function ContextWarehouseSqlWorkspace({
    query,
    results,
    composerValue,
    onQueryChange,
    onRun,
    onComposerChange,
    onComposerSubmit,
}: ContextWarehouseSqlWorkspaceProps): JSX.Element {
    return (
        <div className="@container/context-warehouse-sql space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="mb-0">Revenue by billing interval</h2>
                        <LemonTag size="small">Draft</LemonTag>
                    </div>
                    <p className="mb-0 mt-1 text-sm text-secondary">Connection: PostHog warehouse</p>
                </div>
                <LemonButton data-attr="context-warehouse-run-query" icon={<IconPlay />} onClick={onRun} type="primary">
                    Run
                </LemonButton>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-4 @min-[52rem]/context-warehouse-sql:grid-cols-[minmax(0,3fr)_minmax(18rem,1fr)]">
                <div className="min-w-0 space-y-4">
                    <LemonCard className="overflow-hidden p-0" hoverEffect={false}>
                        <div className="border-b px-3 py-2 text-sm font-semibold">SQL</div>
                        <div className="h-80 min-w-0">
                            <CodeEditor
                                height="100%"
                                language="sql"
                                onChange={(value) => onQueryChange(value ?? '')}
                                options={{
                                    fontSize: 13,
                                    minimap: { enabled: false },
                                    padding: { top: 12, bottom: 12 },
                                    scrollBeyondLastLine: false,
                                    wordWrap: 'on',
                                }}
                                value={query}
                            />
                        </div>
                    </LemonCard>

                    <section className="space-y-2" aria-labelledby="context-warehouse-results-heading">
                        <div className="flex items-center gap-2">
                            <h3 id="context-warehouse-results-heading" className="mb-0 text-base">
                                Results
                            </h3>
                            <LemonBadge.Number count={results.length} maxDigits={2} showZero />
                        </div>
                        <LemonTable
                            data-attr="context-warehouse-query-results"
                            dataSource={results}
                            embedded
                            rowKey="billingInterval"
                            size="small"
                            tableLayout="fixed"
                            columns={[
                                { title: 'Billing interval', dataIndex: 'billingInterval', key: 'billingInterval' },
                                { title: 'Revenue', dataIndex: 'revenue', key: 'revenue' },
                                { title: '7-day change', dataIndex: 'change', key: 'change' },
                            ]}
                        />
                    </section>
                </div>

                <ContextWarehouseAiPanel
                    composerValue={composerValue}
                    onComposerChange={onComposerChange}
                    onComposerSubmit={onComposerSubmit}
                />
            </div>
        </div>
    )
}
