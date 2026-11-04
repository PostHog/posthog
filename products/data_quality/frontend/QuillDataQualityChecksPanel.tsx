import { BindLogic, useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import { CHECKS_CONTAINER } from './checkTableLayout'
import { DataQualityCheckEditorLogicProps, dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillCheckCallout } from './QuillCheckCallout'
import { QuillCheckEditorDialog } from './QuillCheckEditorDialog'
import { QuillChecksPanelBanners } from './QuillChecksPanelBanners'
import { QuillChecksPanelHeader } from './QuillChecksPanelHeader'
import { QuillChecksTable } from './QuillChecksTable'
import { QuillMetricChecksEmptyState } from './QuillMetricChecksEmptyState'
import { QuillRunHistoryDialog } from './QuillRunHistoryDialog'

export interface QuillDataQualityChecksPanelProps extends DataQualityChecksLogicProps {
    columns: DatabaseSchemaField[]
    dataLastSyncedAt?: string | null
    hideTitle?: boolean
    newCheckDisabledReason?: string
    notice?: ReactNode
    subjectName?: string
}

function NoChecksYet({ onAddCheck, disabledReason }: { onAddCheck: () => void; disabledReason?: string }): JSX.Element {
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>No checks yet</EmptyTitle>
                <EmptyDescription>
                    Checks verify this data automatically after each sync or materialization.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    variant="primary"
                    onClick={onAddCheck}
                    disabledReason={disabledReason}
                    data-attr="data-quality-first-check"
                >
                    Add your first check
                </Button>
            </EmptyContent>
        </Empty>
    )
}

export function QuillDataQualityChecksPanel({
    columns,
    subjectName,
    dataLastSyncedAt,
    hideTitle,
    newCheckDisabledReason,
    notice,
    ...logicProps
}: QuillDataQualityChecksPanelProps): JSX.Element | null {
    const logic = dataQualityChecksLogic(logicProps)
    const { checks, checksLoading, checksLoadError, checksLoaded, accessDenied } = useValues(logic)
    const { loadChecks, loadHealth, upsertCheck, runCheck } = useActions(logic)

    const editorProps: DataQualityCheckEditorLogicProps = {
        surface: `subject:${logicProps.subjectType}:${logicProps.subjectId}`,
        onSaved: (check) => {
            upsertCheck(check)
            loadHealth()
        },
        onRunNow: (check) => runCheck(check.id),
    }
    const { openEditor, openEditorWithStarter } = useActions(dataQualityCheckEditorLogic(editorProps))
    const columnNames = columns.map((column) => column.name)
    const outputSchema = columns.map((column) => ({ name: column.name, type: column.type }))
    const addCheck = (): void => openEditor(null, logicProps, columnNames, outputSchema)
    const isMetric = logicProps.subjectType === 'metric'

    if (accessDenied) {
        return isMetric ? (
            <Text size="xs" variant="muted" className="m-0">
                You don't have access to the tests for this metric.
            </Text>
        ) : null
    }

    if (checksLoadError && !checksLoaded) {
        return (
            <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadChecks }}>
                Could not load the checks. Try again.
            </QuillCheckCallout>
        )
    }

    if (!checksLoaded) {
        return <Skeleton className="h-40 w-full" aria-busy="true" />
    }

    if (!checksLoading && checks.length === 0) {
        return (
            <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
                <div className={cn(CHECKS_CONTAINER, 'flex flex-col gap-3')} data-attr="data-quality-checks-panel">
                    {notice}
                    {isMetric ? (
                        <QuillMetricChecksEmptyState
                            metricName={subjectName}
                            onStart={(starterKey) => openEditorWithStarter(logicProps, starterKey)}
                            disabledReason={newCheckDisabledReason}
                        />
                    ) : (
                        <NoChecksYet onAddCheck={addCheck} disabledReason={newCheckDisabledReason} />
                    )}
                    <QuillCheckEditorDialog />
                </div>
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={dataQualityCheckEditorLogic} props={editorProps}>
            <div className={cn(CHECKS_CONTAINER, 'flex flex-col gap-3')} data-attr="data-quality-checks-panel">
                <QuillChecksPanelHeader
                    {...logicProps}
                    hideTitle={hideTitle}
                    onAddCheck={addCheck}
                    newCheckDisabledReason={newCheckDisabledReason}
                />

                {notice}

                {dataLastSyncedAt && (
                    <Text size="xs" variant="muted" className="m-0">
                        Checks test the data from the last sync (synced <TZLabel time={dataLastSyncedAt} />
                        ). After you change this view, sync it to test the new query.
                    </Text>
                )}

                <QuillChecksPanelBanners {...logicProps} />

                <QuillChecksTable {...logicProps} columns={columnNames} outputSchema={outputSchema} />

                <QuillRunHistoryDialog {...logicProps} />

                <QuillCheckEditorDialog />
            </div>
        </BindLogic>
    )
}
