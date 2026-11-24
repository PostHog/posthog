import { useActions, useValues } from 'kea'

import {
    IconBug,
    IconCheck,
    IconClock,
    IconFilter,
    IconFolder,
    IconPlus,
    IconTrending,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, type LemonMenuItems } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { AttentionReasonsEnumApi } from '../../generated/api.schemas'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { ATTENTION_LABELS } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

type StatusFilter = 'any' | AttentionReasonsEnumApi

const STATUS_FILTERS: { value: StatusFilter; label: string; icon: JSX.Element }[] = [
    { value: 'any', label: 'Needs attention', icon: <IconWarning /> },
    { value: 'errored', label: ATTENTION_LABELS.errored, icon: <IconBug /> },
    { value: 'silent', label: ATTENTION_LABELS.silent, icon: <IconClock /> },
    { value: 'worse', label: ATTENTION_LABELS.worse, icon: <IconTrending className="-scale-y-100" /> },
]

function count(value: number): JSX.Element {
    return <span className="text-xs tabular-nums text-secondary">{value}</span>
}

/** One menu for the page's directory and status filters. Active ones show beside it, so they stay easy to remove. */
export function EvaluationQuickFilters(): JSX.Element {
    const { directoryTiles, selectedDirectory, attentionFilter, attentionCounts } = useValues(evaluationsOverviewLogic)
    const { openDirectory, setAttentionFilter } = useActions(evaluationsOverviewLogic)
    const { deletingDirectoryId } = useValues(llmEvaluationsLogic)
    const { selectDirectory, openCreateDirectory, openRenameDirectory, deleteDirectory } =
        useActions(llmEvaluationsLogic)
    const editorReason = getAccessControlDisabledReason(AccessControlResourceType.Evaluation, AccessControlLevel.Editor)
    const activeStatus = STATUS_FILTERS.find(({ value }) => value === attentionFilter)
    const activeCount = Number(!!selectedDirectory) + Number(!!activeStatus)

    const items: LemonMenuItems = [
        {
            items: [
                {
                    label: 'Directory',
                    icon: <IconFolder />,
                    sideIcon: selectedDirectory ? count(1) : undefined,
                    'data-attr': 'evaluation-overview-quick-filter-directory',
                    items: [
                        ...directoryTiles.map(({ directory, evaluationCount, needAttentionCount }) => {
                            const selected = directory.id === selectedDirectory?.id
                            return {
                                label: (
                                    <span className="flex items-center gap-1.5">
                                        <span className="truncate max-w-48">{directory.name}</span>
                                        {needAttentionCount ? (
                                            <span
                                                className="size-1.5 rounded-full bg-danger"
                                                title={`${needAttentionCount} need attention`}
                                            />
                                        ) : null}
                                    </span>
                                ),
                                icon: selected ? <IconCheck /> : <span className="size-4" />,
                                sideIcon: count(evaluationCount),
                                active: selected,
                                onClick: () => (selected ? selectDirectory(null) : openDirectory(directory.id)),
                                'data-attr': 'evaluation-overview-directory-tile',
                            }
                        }),
                        {
                            label: 'New directory',
                            icon: <IconPlus />,
                            onClick: () => openCreateDirectory(),
                            disabledReason: editorReason,
                            'data-attr': 'create-evaluation-directory-button',
                        },
                    ],
                },
            ],
        },
        {
            items: STATUS_FILTERS.map(({ value, label, icon }) => ({
                label,
                icon: attentionFilter === value ? <IconCheck /> : icon,
                sideIcon: count(attentionCounts[value] ?? 0),
                active: attentionFilter === value,
                onClick: () => setAttentionFilter(attentionFilter === value ? null : value),
                'data-attr': `evaluation-overview-table-filter-${value}`,
            })),
        },
        activeCount > 0 && {
            items: [
                {
                    label: 'Clear quick filters',
                    onClick: () => {
                        selectDirectory(null)
                        setAttentionFilter(null)
                    },
                    'data-attr': 'evaluation-overview-clear-quick-filters',
                },
            ],
        },
    ]

    return (
        <>
            <LemonMenu items={items} placement="bottom-start">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconFilter />}
                    active={activeCount > 0}
                    data-attr="evaluation-overview-quick-filters"
                >
                    {activeCount > 0 ? `Quick filters (${activeCount})` : 'Quick filters'}
                </LemonButton>
            </LemonMenu>
            {selectedDirectory && (
                <LemonMenu
                    items={[
                        {
                            label: 'Rename directory',
                            onClick: () => openRenameDirectory(selectedDirectory),
                            disabledReason: editorReason,
                            'data-attr': 'evaluation-overview-directory-rename',
                        },
                        {
                            label: 'Delete directory',
                            status: 'danger',
                            disabledReason: editorReason,
                            'data-attr': 'evaluation-overview-directory-delete',
                            onClick: () => {
                                const tile = directoryTiles.find(
                                    ({ directory }) => directory.id === selectedDirectory.id
                                )
                                LemonDialog.open({
                                    title: `Delete ${selectedDirectory.name}?`,
                                    description: `${pluralize(tile?.evaluationCount ?? 0, 'evaluation')} will move to the top level.`,
                                    primaryButton: {
                                        children: 'Delete directory',
                                        status: 'danger',
                                        onClick: () => deleteDirectory(selectedDirectory.id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            },
                        },
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFolder />}
                        loading={deletingDirectoryId === selectedDirectory.id}
                        data-attr="evaluation-overview-directory-more"
                        sideAction={{
                            icon: <IconX />,
                            tooltip: 'Remove the directory filter',
                            onClick: () => selectDirectory(null),
                            'data-attr': 'evaluation-overview-scope-directory-clear',
                        }}
                    >
                        <span className="truncate max-w-48">{selectedDirectory.name}</span>
                    </LemonButton>
                </LemonMenu>
            )}
            {activeStatus && (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={activeStatus.icon}
                    sideIcon={<IconX className="text-secondary" />}
                    onClick={() => setAttentionFilter(null)}
                    tooltip={`Remove the ${activeStatus.label} filter`}
                    data-attr={`evaluation-overview-table-filter-${activeStatus.value}-remove`}
                >
                    {activeStatus.label}
                </LemonButton>
            )}
        </>
    )
}
