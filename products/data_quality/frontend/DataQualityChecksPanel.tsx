import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { CheckEditorModal } from './CheckEditorModal'
import { HEALTH_LABELS, HEALTH_TAG_TYPES } from './checksConstants'
import { ChecksTable } from './ChecksTable'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { SuiteRunsHistory } from './SuiteRunsHistory'

interface DataQualityChecksPanelProps extends DataQualityChecksLogicProps {
    columns: DatabaseSchemaField[]
    dataLastSyncedAt?: string | null
    /** Drops the "Data quality" heading where the surface already names the panel, such as a tab. */
    hideTitle?: boolean
}

export function DataQualityChecksPanel({
    columns,
    dataLastSyncedAt,
    hideTitle,
    ...logicProps
}: DataQualityChecksPanelProps): JSX.Element | null {
    const logic = dataQualityChecksLogic(logicProps)
    const {
        health,
        checks,
        checksLoading,
        enabledChecksCount,
        isSuiteRunning,
        pollTimedOut,
        runAllInFlight,
        accessDenied,
    } = useValues(logic)
    const { runAll, loadChecks, loadHealth, upsertCheck, runCheck } = useActions(logic)

    const editorProps: DataQualityCheckEditorLogicProps = {
        surface: `subject:${logicProps.subjectType}:${logicProps.subjectId}`,
        onSaved: (check) => {
            upsertCheck(check)
            loadHealth()
        },
        onRunNow: (check) => runCheck(check.id),
    }
    const { openEditor } = useActions(dataQualityCheckEditorLogic(editorProps))
    const columnNames = columns.map((column) => column.name)
    const addCheck = (): void => openEditor(null, logicProps, columnNames)

    if (accessDenied) {
        return null
    }

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <div className="flex flex-col gap-2 mt-4">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                        {!hideTitle && <h3 className="mb-0 text-lg font-semibold">Data quality</h3>}
                        {health && (
                            <LemonTag type={HEALTH_TAG_TYPES[health.health] ?? 'default'}>
                                {HEALTH_LABELS[health.health] ?? health.health}
                            </LemonTag>
                        )}
                        {health && health.checks_total > 0 && (
                            <span className="text-secondary text-sm">
                                {health.checks_failing} of {health.checks_total} failing
                            </span>
                        )}
                        {health?.health === 'unknown' && (
                            <span className="text-secondary text-sm">Run checks to see health</span>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={runAll}
                            loading={runAllInFlight || isSuiteRunning}
                            disabledReason={
                                checksLoading
                                    ? 'Loading checks'
                                    : enabledChecksCount === 0
                                      ? 'No enabled checks to run'
                                      : undefined
                            }
                            data-attr="data-quality-run-all"
                        >
                            Run all checks
                        </LemonButton>
                        <LemonButton type="primary" size="small" onClick={addCheck} data-attr="data-quality-new-check">
                            New check
                        </LemonButton>
                    </div>
                </div>

                {dataLastSyncedAt && (
                    <p className="mb-0 text-secondary text-sm">
                        Checks test the data from the last sync (synced <TZLabel time={dataLastSyncedAt} />
                        ). After you change this view, sync it to test the new query.
                    </p>
                )}

                {isSuiteRunning && (
                    <LemonBanner type="info" icon={<Spinner />}>
                        Running checks...
                    </LemonBanner>
                )}
                {pollTimedOut && (
                    <LemonBanner
                        type="warning"
                        action={{
                            children: 'Refresh',
                            onClick: () => {
                                loadChecks()
                                loadHealth()
                            },
                        }}
                    >
                        Checks are still running. Check back in a few minutes.
                    </LemonBanner>
                )}

                {!checksLoading && checks.length === 0 ? (
                    <NoChecksYet onAddCheck={addCheck} />
                ) : (
                    <ChecksTable {...logicProps} columns={columnNames} />
                )}

                <SuiteRunsHistory {...logicProps} />

                <CheckEditorModal />
            </div>
        </BindLogic>
    )
}

function NoChecksYet({ onAddCheck }: { onAddCheck: () => void }): JSX.Element {
    return (
        <div className="border rounded p-4 flex flex-col items-start gap-2">
            <h4 className="mb-0">No checks yet</h4>
            <p className="mb-0 text-secondary">
                Checks verify this data automatically after each sync or materialization.
            </p>
            <LemonButton type="primary" size="small" onClick={onAddCheck} data-attr="data-quality-first-check">
                Add your first check
            </LemonButton>
        </div>
    )
}
