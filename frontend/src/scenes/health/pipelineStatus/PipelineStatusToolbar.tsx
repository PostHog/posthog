import { useActions, useValues } from 'kea'

import { IconCheck, IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonSegmentedButton } from '@posthog/lemon-ui'

import { pipelineStatusSceneLogic } from './pipelineStatusSceneLogic'
import type { IssueTypeFilter } from './pipelineStatusSceneLogic'

const TYPE_FILTER_OPTIONS: { value: IssueTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'materialized_view', label: 'Views' },
    { value: 'external_data_sync', label: 'Syncs' },
    { value: 'source', label: 'Sources' },
    { value: 'destination', label: 'Destinations' },
    { value: 'transformation', label: 'Transformations' },
]

export function PipelineStatusToolbar(): JSX.Element {
    const { typeFilter, searchTerm, showDismissed, dismissedCount } = useValues(pipelineStatusSceneLogic)
    const { setTypeFilter, setSearchTerm, setShowDismissed } = useActions(pipelineStatusSceneLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonSegmentedButton
                value={typeFilter}
                onChange={(value) => setTypeFilter(value as IssueTypeFilter)}
                options={TYPE_FILTER_OPTIONS}
                size="small"
            />
            <LemonInput
                type="search"
                placeholder="Search issues..."
                onChange={setSearchTerm}
                value={searchTerm}
                className="max-w-60"
            />
            <div className="ml-auto">
                <LemonMenu
                    items={[
                        {
                            label: `Show dismissed${dismissedCount > 0 ? ` (${dismissedCount})` : ''}`,
                            icon: showDismissed ? <IconCheck /> : undefined,
                            onClick: () => setShowDismissed(!showDismissed),
                        },
                    ]}
                    placement="bottom-end"
                >
                    <LemonButton icon={<IconEllipsis />} type="tertiary" size="small" />
                </LemonMenu>
            </div>
        </div>
    )
}
