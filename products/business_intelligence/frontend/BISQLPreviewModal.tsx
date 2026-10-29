import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { biSceneLogic } from './biSceneLogic'

export function BISQLPreviewModal(): JSX.Element {
    const {
        sqlPreviewOpen,
        sqlPreviewVersion,
        sqlPreviewQuery,
        sqlEditorUrl,
        generatedQuery,
        lastRunQuery,
        displayedQueryIsCurrent,
    } = useValues(biSceneLogic)
    const { setSqlPreviewOpen, setSqlPreviewVersion } = useActions(biSceneLogic)
    const source = sqlPreviewQuery?.source

    return (
        <LemonModal
            isOpen={sqlPreviewOpen}
            onClose={() => setSqlPreviewOpen(false)}
            title="Worksheet SQL"
            width={800}
            footer={
                <div className="flex flex-wrap justify-end gap-2">
                    <LemonButton type="secondary" onClick={() => setSqlPreviewOpen(false)}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={sqlEditorUrl ?? undefined}
                        targetBlank
                        disabledReason={!sqlEditorUrl ? 'No query available' : undefined}
                        data-attr="bi-open-sql-editor"
                    >
                        Open in SQL editor
                    </LemonButton>
                </div>
            }
        >
            <div className="flex min-w-0 flex-col gap-3" data-attr="bi-sql-preview">
                <LemonSegmentedButton
                    value={sqlPreviewVersion}
                    onChange={setSqlPreviewVersion}
                    options={[
                        {
                            value: 'current',
                            label: 'Current worksheet',
                            disabledReason: !generatedQuery
                                ? 'Select fields and resolve query errors first'
                                : undefined,
                        },
                        {
                            value: 'last_run',
                            label: 'Last run',
                            disabledReason: !lastRunQuery ? 'Run the worksheet first' : undefined,
                        },
                    ]}
                />
                {!displayedQueryIsCurrent && sqlPreviewVersion === 'current' && (
                    <LemonBanner type="info">This query includes worksheet changes that have not been run.</LemonBanner>
                )}
                {source ? (
                    <>
                        <CodeSnippet language={Language.SQL} wrap>
                            {source.query}
                        </CodeSnippet>
                        <p className="m-0 text-secondary">
                            Copy copies the query text. Open in SQL editor carries its connection, filters, and variable
                            values into a new tab, ready to run.
                        </p>
                        {(source.filters || source.variables || source.values) && (
                            <details>
                                <summary className="cursor-pointer">Query parameters</summary>
                                <CodeSnippet language={Language.JSON} wrap>
                                    {JSON.stringify(
                                        { filters: source.filters, variables: source.variables, values: source.values },
                                        null,
                                        2
                                    )}
                                </CodeSnippet>
                            </details>
                        )}
                        {sqlPreviewVersion === 'last_run' && (
                            <p className="m-0 text-secondary">
                                Relative dates are evaluated again when the query runs.
                            </p>
                        )}
                    </>
                ) : (
                    <p>No query is available for this selection.</p>
                )}
            </div>
        </LemonModal>
    )
}
