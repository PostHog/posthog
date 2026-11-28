import { Callout, CalloutActions, CalloutContent, CalloutDescription, CalloutIcon, CalloutTitle } from '@posthog/quill'

import { QuillFixErrorButton } from 'products/data_warehouse/frontend/sql_editor/workspace/QuillFixErrorButton'

import { EditorQueryScanBanner } from './components/EditorQueryScanBanner'

export function QuillOutputErrorState({
    error,
    cancelled,
    showQueryScan,
}: {
    error: string | null | undefined
    cancelled: boolean
    showQueryScan: boolean
}): JSX.Element {
    return (
        <div
            className="absolute inset-0 flex flex-col gap-2 overflow-auto p-3"
            data-attr="sql-editor-output-pane-error"
        >
            <Callout tone={cancelled ? 'default' : 'destructive'}>
                <CalloutIcon />
                <CalloutContent>
                    <CalloutTitle>{cancelled ? 'The query was cancelled' : 'The query failed'}</CalloutTitle>
                    {!cancelled && error ? (
                        <CalloutDescription>
                            <pre
                                className="m-0 max-h-60 overflow-auto font-mono text-xs whitespace-pre-wrap break-words"
                                translate="no"
                            >
                                {error}
                            </pre>
                        </CalloutDescription>
                    ) : null}
                </CalloutContent>
                {!cancelled ? (
                    <CalloutActions>
                        <QuillFixErrorButton source="query-error" label="Fix error with AI" />
                    </CalloutActions>
                ) : null}
            </Callout>
            {showQueryScan ? <EditorQueryScanBanner /> : null}
        </div>
    )
}
