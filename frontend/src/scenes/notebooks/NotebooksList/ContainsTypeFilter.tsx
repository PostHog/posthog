import { NotebookNodeType } from '~/types'
import { NotebooksListFilters } from 'scenes/notebooks/Notebook/notebooksListLogic'
import { LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

export const fromNodeTypeToLabel: Omit<Record<NotebookNodeType, string>, NotebookNodeType.Backlink> = {
    [NotebookNodeType.FeatureFlag]: 'Feature flag',
    [NotebookNodeType.Image]: 'Image',
    [NotebookNodeType.Insight]: 'Insight',
    [NotebookNodeType.Person]: 'Person',
    [NotebookNodeType.Query]: 'Query',
    [NotebookNodeType.Recording]: 'Session replay',
    [NotebookNodeType.RecordingPlaylist]: 'Session replay playlist',
    [NotebookNodeType.ReplayTimestamp]: 'Session replay comment',
}

export function ContainsTypeFilters({
    filters,
    setFilters,
}: {
    filters: NotebooksListFilters
    setFilters: (selection: Partial<NotebooksListFilters>) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span>Containing:</span>
            <LemonButtonWithDropdown
                status="stealth"
                type="secondary"
                data-attr={'notebooks-list-contains-filters'}
                dropdown={{
                    sameWidth: false,
                    closeOnClickInside: false,
                    overlay: [
                        <>
                            {Object.entries(fromNodeTypeToLabel)
                                .filter((entry) => entry[1] !== '')
                                .map(([type, label]) => {
                                    const nodeType = type as NotebookNodeType
                                    return (
                                        <LemonCheckbox
                                            key={type}
                                            size="small"
                                            fullWidth
                                            checked={filters.contains.includes(nodeType)}
                                            onChange={(checked) => {
                                                const changedContains = filters.contains.filter((x) => x !== nodeType)
                                                if (checked) {
                                                    changedContains.push(nodeType)
                                                }
                                                setFilters({ contains: changedContains })
                                            }}
                                            label={label}
                                        />
                                    )
                                })}
                        </>,
                    ],
                    actionable: true,
                }}
            >
                <span className={'text-muted'}>
                    {filters.contains.length === 0
                        ? 'Any types'
                        : filters.contains.length === 1
                        ? fromNodeTypeToLabel[filters.contains[0] as NotebookNodeType]
                        : `${filters.contains.length} types selected`}
                </span>
            </LemonButtonWithDropdown>
        </div>
    )
}
