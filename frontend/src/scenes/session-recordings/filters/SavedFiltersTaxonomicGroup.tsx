import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { TaxonomicFilterRenderProps } from 'lib/components/TaxonomicFilter/types'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { SessionRecordingPlaylistType } from '~/types'

export function SavedFiltersTaxonomicGroup({
    onChange,
    infiniteListLogicProps,
}: Pick<TaxonomicFilterRenderProps, 'onChange' | 'infiniteListLogicProps'>): JSX.Element {
    const { items, searchQuery, isLoading } = useValues(infiniteListLogic(infiniteListLogicProps))

    const filters = items.results as unknown as SessionRecordingPlaylistType[]
    const hasResults = filters.length > 0

    if (isLoading && !hasResults) {
        return (
            <div className="px-3 py-2 space-y-2">
                <LemonSkeleton className="h-7 w-full" />
                <LemonSkeleton className="h-7 w-4/5" />
                <LemonSkeleton className="h-7 w-3/5" />
            </div>
        )
    }

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
