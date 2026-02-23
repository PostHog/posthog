import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterRenderProps } from 'lib/components/TaxonomicFilter/types'

import { SessionRecordingPlaylistType } from '~/types'

import { sessionRecordingSavedFiltersLogic } from './sessionRecordingSavedFiltersLogic'

export function SavedFiltersTaxonomicGroup({
    onChange,
    infiniteListLogicProps,
}: Pick<TaxonomicFilterRenderProps, 'onChange' | 'infiniteListLogicProps'>): JSX.Element {
    const { items, searchQuery } = useValues(infiniteListLogic(infiniteListLogicProps))
    const { requestApplySavedFilter } = sessionRecordingSavedFiltersLogic.actions

    const filters = items.results as unknown as SessionRecordingPlaylistType[]
    const hasResults = filters.length > 0

    return (
        <div className="px-1 pt-1.5 pb-2.5">
            {hasResults ? (
                <ul className="gap-y-px">
                    {filters.map((filter) => {
                        const name = filter.name || filter.derived_name || 'Unnamed'
                        return (
                            <LemonButton
                                key={filter.short_id}
                                size="small"
                                fullWidth
                                onClick={() => {
                                    requestApplySavedFilter(filter)
                                    onChange(filter.short_id, filter)
                                }}
                            >
                                {name}
                            </LemonButton>
                        )
                    })}
                </ul>
            ) : (
                <div className="p-2 text-secondary text-center">
                    {searchQuery ? 'No saved filters match your search' : 'No saved filters yet'}
                </div>
            )}
        </div>
    )
}
