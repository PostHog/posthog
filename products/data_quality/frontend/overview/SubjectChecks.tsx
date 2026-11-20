import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { CheckRunsTable } from '../CheckRunsTable'
import { checkDisplayName, checkTypeLabel } from '../checksConstants'
import { CheckStatusCell } from '../CheckStatusCell'
import { dataQualityCheckEditorLogic } from '../dataQualityCheckEditorLogic'
import type { DataQualityOverviewCheckApi } from '../generated/api.schemas'
import {
    SubjectGroup,
    dataQualityOverviewLogic,
    focusCandidatesAfterDelete,
    rowActionsId,
} from './dataQualityOverviewLogic'
import { focusFirstAvailable } from './focusFirstAvailable'

export function SubjectChecks({ group }: { group: SubjectGroup }): JSX.Element {
    const { checkRunsByCheckId, runsLoadingByCheckId, deletingCheckIds, subjectGroups, startingRun, isRunning } =
        useValues(dataQualityOverviewLogic)
    const { loadCheckRuns, deleteCheck, setLastActionCheck, openFailingRows, runChecks } =
        useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const confirmDelete = (check: DataQualityOverviewCheckApi): void => {
        const fallbacks = focusCandidatesAfterDelete(subjectGroups, group.subjectKey, check.id)
        LemonDialog.open({
            title: 'Delete this check?',
            description: 'Past run history is kept.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => {
                    deleteCheck(check)
                    focusFirstAvailable(fallbacks)
                },
            },
            secondaryButton: {
                children: 'Cancel',
                onClick: () => focusFirstAvailable([rowActionsId(check.id)]),
            },
        })
    }

    return (
        <LemonTable
            size="small"
            dataSource={group.checks}
            rowKey="id"
            nouns={['check', 'checks']}
            expandable={{
                onRowExpand: (check) => loadCheckRuns(check),
                expandedRowRender: (check) => (
                    <div className="flex flex-col gap-2 py-2">
                        {check.description && <p className="mb-0 text-secondary">{check.description}</p>}
                        <CheckRunsTable
                            runs={checkRunsByCheckId[check.id] ?? []}
                            loading={runsLoadingByCheckId[check.id]}
                        />
                    </div>
                ),
            }}
            columns={[
                { title: 'Check', key: 'name', render: (_, check) => checkDisplayName(check) },
                { title: 'Type', key: 'check_type', render: (_, check) => checkTypeLabel(check.check_type) },
                { title: 'Column', key: 'column_name', render: (_, check) => check.column_name || '-' },
                {
                    title: 'Last status',
                    key: 'last_status',
                    render: (_, check) => <CheckStatusCell check={check} />,
                },
                {
                    title: 'Last run',
                    key: 'last_run_at',
                    render: (_, check) => (check.last_run_at ? <TZLabel time={check.last_run_at} /> : '-'),
                },
                {
                    key: 'actions',
                    width: 0,
                    render: (_, check) => (
                        <LemonMenu
                            items={[
                                {
                                    // Reported into this subject's panel, since that is where its
                                    // result lands either way.
                                    label: 'Run now',
                                    onClick: () =>
                                        runChecks({ kind: 'subject', subjectKey: group.subjectKey }, [check.id]),
                                    disabledReason: startingRun || isRunning ? 'Checks are already running' : undefined,
                                },
                                {
                                    label: 'Edit',
                                    onClick: () => {
                                        setLastActionCheck(check.id)
                                        openEditor(check, {
                                            subjectType: check.subject_type,
                                            subjectId: check.subject_uuid ?? '',
                                        })
                                    },
                                },
                                {
                                    label: 'Open failing rows in SQL editor',
                                    tooltip: "The query behind this check's latest run",
                                    onClick: () => openFailingRows(check),
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => confirmDelete(check),
                                    disabledReason: deletingCheckIds[check.id]
                                        ? 'This check is being deleted'
                                        : undefined,
                                },
                            ]}
                        >
                            <LemonButton
                                id={rowActionsId(check.id)}
                                size="small"
                                icon={<IconEllipsis />}
                                data-attr="data-quality-overview-check-actions"
                                aria-label={`Actions for check ${checkDisplayName(check)}`}
                            />
                        </LemonMenu>
                    ),
                },
            ]}
        />
    )
}
