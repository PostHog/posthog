import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, LemonSwitch, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { CheckRunsTable } from './CheckRunsTable'
import { SEVERITY_TAG_TYPES, checkDisplayName, checkTypeLabel } from './checksConstants'
import { CheckStatusCell } from './CheckStatusCell'
import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { DataQualityChecksLogicProps, dataQualityChecksLogic } from './dataQualityChecksLogic'
import type { DataQualityCheckApi } from './generated/api.schemas'

interface ChecksTableProps extends DataQualityChecksLogicProps {
    columns: string[]
}

export function ChecksTable({ columns, ...props }: ChecksTableProps): JSX.Element {
    const logic = dataQualityChecksLogic(props)
    const { sortedChecks, checksLoading, pendingCheckActions, checkRunsByCheckId } = useValues(logic)
    const { deleteCheck, toggleCheckEnabled, runCheck, loadCheckRuns, openFailingRows } = useActions(logic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)

    const confirmDelete = (check: DataQualityCheckApi): void => {
        LemonDialog.open({
            title: 'Delete this check?',
            description: 'Past run history is kept.',
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteCheck(check.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <LemonTable
            rowKey="id"
            dataSource={sortedChecks}
            loading={checksLoading}
            nouns={['check', 'checks']}
            expandable={{
                onRowExpand: (check) => loadCheckRuns(check.id),
                expandedRowRender: (check) => (
                    <div className="flex flex-col gap-2 py-2">
                        {check.description && <p className="mb-0 text-secondary">{check.description}</p>}
                        <CheckRunsTable
                            runs={checkRunsByCheckId[check.id] ?? []}
                            loading={pendingCheckActions.loadingRuns[check.id]}
                        />
                    </div>
                ),
            }}
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    render: (_, check) => (
                        <div className="flex items-center gap-2">
                            <Tooltip title={check.description || undefined}>
                                <span className="font-semibold">{checkDisplayName(check)}</span>
                            </Tooltip>
                            {check.created_source === 'ai_generated' && (
                                <Tooltip title={aiTooltip(check)}>
                                    <LemonTag type="completion">AI</LemonTag>
                                </Tooltip>
                            )}
                            {check.owner && <span className="text-secondary text-xs">{check.owner}</span>}
                        </div>
                    ),
                },
                {
                    title: 'Type',
                    key: 'check_type',
                    render: (_, check) => checkTypeLabel(check.check_type),
                },
                {
                    title: 'Column',
                    key: 'column_name',
                    render: (_, check) => check.column_name || '-',
                },
                {
                    title: 'Severity',
                    key: 'severity',
                    render: (_, check) => (
                        <LemonTag type={SEVERITY_TAG_TYPES[check.severity ?? 'error'] ?? 'default'}>
                            {check.severity ?? 'error'}
                        </LemonTag>
                    ),
                },
                {
                    title: 'Enabled',
                    key: 'enabled',
                    render: (_, check) => (
                        <LemonSwitch
                            checked={check.enabled !== false}
                            onChange={(enabled) => toggleCheckEnabled(check.id, enabled)}
                            disabled={!!pendingCheckActions.toggling[check.id]}
                            aria-label={`Enable check ${checkDisplayName(check)}`}
                        />
                    ),
                },
                {
                    title: 'Last status',
                    key: 'last_status',
                    render: (_, check) => <CheckStatusCell check={check} />,
                },
                {
                    title: 'Last run',
                    tooltip: 'When the check last ran, not when the data was last synced.',
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
                                    label: 'Run now',
                                    onClick: () => runCheck(check.id),
                                    disabledReason: pendingCheckActions.running[check.id]
                                        ? 'This check is already starting'
                                        : undefined,
                                },
                                { label: 'Edit', onClick: () => openEditor(check, props, columns) },
                                {
                                    label: 'Open failing rows in SQL editor',
                                    tooltip: "The query behind this check's latest run",
                                    onClick: () => openFailingRows(check.id),
                                },
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => confirmDelete(check),
                                    disabledReason: pendingCheckActions.deleting[check.id]
                                        ? 'This check is being deleted'
                                        : undefined,
                                },
                            ]}
                        >
                            <LemonButton
                                size="small"
                                icon={<IconEllipsis />}
                                data-attr="data-quality-check-actions"
                                aria-label={`Actions for check ${checkDisplayName(check)}`}
                            />
                        </LemonMenu>
                    ),
                },
            ]}
        />
    )
}

function aiTooltip(check: DataQualityCheckApi): string {
    const confidence =
        check.confidence !== null && check.confidence !== undefined ? `${check.confidence} confidence` : ''
    return [confidence, check.reasoning].filter(Boolean).join('. ') || 'Written by an agent'
}
