import { kea } from 'kea'
import { InsightLogicProps, FilterType, PathType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { PathsFilter } from '~/queries/schema'

import type { pathsDataLogicType } from './pathsDataLogicType'

export const DEFAULT_STEP_LIMIT = 5

export const pathOptionsToLabels = {
    [PathType.PageView]: 'Page views (Web)',
    [PathType.Screen]: 'Screen views (Mobile)',
    [PathType.CustomEvent]: 'Custom events',
}

export const pathOptionsToProperty = {
    [PathType.PageView]: '$current_url',
    [PathType.Screen]: '$screen_name',
    [PathType.CustomEvent]: 'custom_event',
}

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'
export interface PathResult {
    paths: PathNode[]
    filter: Partial<FilterType>
    error?: boolean
}

export interface PathNode {
    target: string
    source: string
    value: number
}

export const pathsDataLogic = kea<pathsDataLogicType>({
    path: (key) => ['scenes', 'paths', 'pathsDataLogic', key],
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY),

    connect: (props: InsightLogicProps) => ({
        values: [insightDataLogic(props), ['insightFilter']],
        actions: [insightDataLogic(props), ['updateInsightFilter']],
    }),

    actions: {
        setIncludeEventTypes: (includeEventTypes: PathType[]) => ({ includeEventTypes }),
    },
    listeners: ({ actions }) => ({
        setIncludeEventTypes: ({ includeEventTypes }) => {
            actions.updateInsightFilter({ include_event_types: includeEventTypes })
        },
    }),
    selectors: {
        includeEventTypes: [
            (s) => [s.insightFilter],
            (insightFilter: PathsFilter | undefined) => {
                return insightFilter?.include_event_types
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.insightFilter],
            (insightFilter: PathsFilter | undefined) => {
                const taxonomicGroupTypes: TaxonomicFilterGroupType[] = []
                if (insightFilter?.include_event_types) {
                    if (insightFilter?.include_event_types.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (insightFilter?.include_event_types.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (insightFilter?.include_event_types.includes(PathType.CustomEvent)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.CustomEvents)
                    }
                }
                taxonomicGroupTypes.push(TaxonomicFilterGroupType.Wildcards)
                return taxonomicGroupTypes
            },
        ],
    },
})
