import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { biEditorLogic } from './biEditorLogic'
import { hierarchyError, hierarchyFieldKey } from './biHierarchies'
import { BIHierarchyImportModal } from './BIHierarchyImportModal'
import { biHierarchyLogic } from './biHierarchyLogic'
import { BIHierarchyModal } from './BIHierarchyModal'

export function BIHierarchySection({ tabId }: { tabId: string }): JSX.Element {
    const { config, dataPaneSearch } = useValues(biEditorLogic({ tabId }))
    const { removeHierarchy } = useActions(biEditorLogic({ tabId }))
    const { editHierarchy, openImport, startHierarchy } = useActions(biHierarchyLogic({ tabId }))
    return (
        <div className="px-1 py-2">
            <div className="flex items-center justify-between gap-1">
                <span className="text-xs font-semibold text-secondary">Hierarchies</span>
                <LemonMenu
                    items={[
                        { label: 'Create hierarchy', onClick: () => editHierarchy() },
                        { label: 'Import from worksheet', onClick: openImport },
                    ]}
                >
                    <LemonButton size="xsmall" icon={<IconPlus />} aria-label="Add hierarchy" />
                </LemonMenu>
            </div>
            {(config.hierarchies ?? [])
                .filter((hierarchy) =>
                    [hierarchy.name, ...hierarchy.levels.map((level) => level.name)].some((name) =>
                        name.toLowerCase().includes(dataPaneSearch.toLowerCase())
                    )
                )
                .map((hierarchy) => (
                    <div key={hierarchy.id} className="flex min-w-0 flex-wrap items-center gap-1">
                        <LemonButton
                            size="xsmall"
                            className="min-w-0 flex-1"
                            tooltip={hierarchy.levels.map((level) => level.name).join(' → ')}
                            aria-label={hierarchy.name}
                            disabledReason={hierarchyError(hierarchy, config)}
                            onClick={() => startHierarchy(hierarchy.id, 'rows')}
                        >
                            <span className="truncate">{hierarchy.name}</span>
                        </LemonButton>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Start on rows',
                                    disabledReason: hierarchyError(hierarchy, config),
                                    onClick: () => startHierarchy(hierarchy.id, 'rows'),
                                },
                                {
                                    label: 'Start on columns',
                                    disabledReason: hierarchyError(hierarchy, config),
                                    onClick: () => startHierarchy(hierarchy.id, 'columns'),
                                },
                                { label: 'Edit hierarchy', onClick: () => editHierarchy(hierarchy) },
                                {
                                    label: 'Delete hierarchy',
                                    status: 'danger',
                                    onClick: () => removeHierarchy(hierarchy.id),
                                },
                            ]}
                        >
                            <LemonButton
                                icon={<IconEllipsis />}
                                size="xsmall"
                                aria-label={`Options for hierarchy ${hierarchy.name}`}
                            />
                        </LemonMenu>
                        <div className="w-full break-words px-2 text-xs text-secondary">
                            {hierarchy.levels
                                .map((level) =>
                                    [...config.rows, ...config.columns].some(
                                        (field) => hierarchyFieldKey(field) === hierarchyFieldKey(level)
                                    )
                                        ? `${level.name} (current)`
                                        : level.name
                                )
                                .join(' → ')}
                            <div>
                                {hierarchy.levels.length > 0 &&
                                [...config.rows, ...config.columns].some(
                                    (field) =>
                                        hierarchyFieldKey(field) ===
                                        hierarchyFieldKey(hierarchy.levels[hierarchy.levels.length - 1])
                                )
                                    ? 'Last level. Use the drill path to return to a parent.'
                                    : 'Click a result to drill to the next level.'}
                            </div>
                        </div>
                    </div>
                ))}
            <BIHierarchyModal tabId={tabId} />
            <BIHierarchyImportModal tabId={tabId} />
        </div>
    )
}
