import { useMountedLogic, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import {
    DATA_INTERVAL_END_PLACEHOLDER,
    DATA_INTERVAL_START_PLACEHOLDER,
    batchExportHogQLEditorTabId,
    batchExportHogQLQueryLogic,
} from './batchExportHogQLQueryLogic'

export function BatchExportHogQLQueryEditor(): JSX.Element {
    const { props: formLogicProps } = useMountedLogic(batchExportConfigFormLogic)
    const { previewStart, previewEnd, projectTimezone, usesIntervalPlaceholders } = useValues(
        batchExportHogQLQueryLogic(formLogicProps)
    )

    return (
        <div className="flex flex-col gap-2">
            {!usesIntervalPlaceholders && (
                <LemonBanner type="warning">
                    This query doesn't use {`{${DATA_INTERVAL_START_PLACEHOLDER}}`} or{' '}
                    {`{${DATA_INTERVAL_END_PLACEHOLDER}}`}, so every run exports all of its results. To export only new
                    data on each run, filter on these placeholders.
                </LemonBanner>
            )}
            {/* Fixed height, because the embedded editor fills its container and has no height of its own */}
            <div className="h-160 border rounded overflow-hidden flex flex-col">
                <SQLEditor
                    tabId={batchExportHogQLEditorTabId(formLogicProps)}
                    mode={SQLEditorMode.Embedded}
                    defaultShowDatabaseTree={false}
                    singleStatement
                    hideAgentHints
                    hideVariables
                    hideFilters
                />
            </div>
            <p className="text-xs text-secondary mb-0">
                When you run the query here, the placeholders cover the last complete interval:{' '}
                <span translate="no">{`'${previewStart}'`}</span> to <span translate="no">{`'${previewEnd}'`}</span>{' '}
                <span translate="no">{`(${projectTimezone})`}</span>. Each export run fills them with its own interval.
            </p>
        </div>
    )
}
