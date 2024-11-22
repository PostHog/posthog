import { LemonCheckbox, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { NewButton } from 'scenes/pipeline/NewButton'

import { PipelineStage } from '~/types'

import { PipelineBackend } from '../types'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'

export type DestinationsFiltersProps = {
    hideSearch?: boolean
    hideShowPaused?: boolean
    hideKind?: boolean
    askForFeedback?: boolean
}

export function DestinationsFilters({
    hideSearch,
    hideShowPaused,
    hideKind,
    askForFeedback = true,
}: DestinationsFiltersProps): JSX.Element | null {
    const { filters } = useValues(destinationsFiltersLogic)
    const { setFilters, openFeedbackDialog } = useActions(destinationsFiltersLogic)

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                {!hideSearch && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
                {askForFeedback ? (
                    <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog()}>
                        Can't find what you're looking for?
                    </Link>
                ) : null}
                <div className="flex-1" />
                {typeof hideShowPaused !== 'boolean' && (
                    <LemonCheckbox
                        label="Show paused"
                        bordered
                        size="small"
                        checked={filters.showPaused}
                        onChange={(e) => setFilters({ showPaused: e ?? undefined })}
                    />
                )}
                {!hideKind && (
                    <LemonSelect
                        type="secondary"
                        size="small"
                        options={
                            [
                                { label: 'All kinds', value: null },
                                { label: 'Realtime', value: PipelineBackend.HogFunction },
                                { label: 'Batch exports', value: PipelineBackend.BatchExport },
                            ].filter(Boolean) as { label: string; value: PipelineBackend | null }[]
                        }
                        value={filters.kind ?? null}
                        onChange={(e) => setFilters({ kind: e ?? null })}
                    />
                )}
                {askForFeedback ? null : <NewButton stage={PipelineStage.Destination} size="small" />}
            </div>
        </div>
    )
}
