import { IconRewindPlay } from '@posthog/icons'

import { Command, GLOBAL_COMMAND_SCOPE } from 'lib/components/CommandPalette/commandPaletteLogic'
import { isURL } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingDurationFilter,
    RecordingUniversalFilters,
    ReplayTabs,
} from '~/types'

function isUUIDLike(candidate: string): boolean {
    return candidate.length === 36 && !!candidate.toLowerCase().match(/^[0-9a-f-]+$/)?.length
}

export const WATCH_RECORDINGS_OF_KEY = 'watch-recordings-of'
export const watchRecordingsOfCommand = (
    push: (
        url: string,
        searchInput?: string | Record<string, any> | undefined,
        hashInput?: string | Record<string, any> | undefined
    ) => void
): Command => ({
    key: WATCH_RECORDINGS_OF_KEY,
    scope: GLOBAL_COMMAND_SCOPE,
    resolver: (argument: string | undefined) => {
        if (argument === undefined) {
            return null
        }

        const replayFilter = (
            key: 'snapshot_source' | 'visited_page',
            value: string
        ): Partial<RecordingUniversalFilters> => ({
            date_from: '-3d',
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                key: key,
                                value: [value],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Recording,
                            },
                        ],
                    },
                ],
            },
            duration: [
                {
                    type: PropertyFilterType.Recording,
                    key: 'duration',
                    value: 1,
                    operator: 'gt',
                } as RecordingDurationFilter,
            ],
        })

        const words = argument.split(' ')
        if (words.includes('web') || words.includes('mobile')) {
            return {
                icon: IconRewindPlay,
                display: `Watch ${argument} recordings`,
                executor: () => {
                    push(urls.replay(ReplayTabs.Home, replayFilter('snapshot_source', argument)))
                },
            }
        }

        const url = words.find((word) => isURL(word))
        if (url) {
            return {
                icon: IconRewindPlay,
                display: `Watch recordings of visits to ${url}`,
                executor: () => {
                    push(urls.replay(ReplayTabs.Home, replayFilter('visited_page', url)))
                },
            }
        }

        const uuid = words.find((word) => isUUIDLike(word))
        if (uuid) {
            return {
                icon: IconRewindPlay,
                display: `Watch recording of session: ${uuid}`,
                executor: () => {
                    push(urls.replaySingle(uuid))
                },
            }
        }

        return null
    },
})
