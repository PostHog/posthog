import { kea, path, props, key, connect, selectors } from 'kea'
import { InsightLogicProps, FilterType, PathType } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { pathsDataLogicType } from './pathsDataLogicType'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isPathsQuery } from '~/queries/utils'

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

export const pathsDataLogic = kea<pathsDataLogicType>([
    path((key) => ['scenes', 'paths', 'pathsDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightQuery',
                'insightData',
                'insightDataLoading',
                'insightDataError',
                'pathsFilter',
            ],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter']],
    })),

    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): PathNode[] => {
                return isPathsQuery(insightQuery) ? insightData?.result ?? [] : []
            },
        ],
        paths: [
            (s) => [s.results],
            (results) => {
                const nodes: Record<string, any> = {}
                for (const path of results) {
                    if (!nodes[path.source]) {
                        nodes[path.source] = { name: path.source }
                    }
                    if (!nodes[path.target]) {
                        nodes[path.target] = { name: path.target }
                    }
                }

                return {
                    nodes: Object.values(nodes),
                    links: results,
                }
            },
        ],
        pathsLoading: [(s) => [s.insightDataLoading], (insightDataLoading) => insightDataLoading],
        taxonomicGroupTypes: [
            (s) => [s.pathsFilter],
            (pathsFilter) => {
                const taxonomicGroupTypes: TaxonomicFilterGroupType[] = []
                if (pathsFilter?.include_event_types) {
                    if (pathsFilter?.include_event_types.includes(PathType.PageView)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.PageviewUrls)
                    }
                    if (pathsFilter?.include_event_types.includes(PathType.Screen)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.Screens)
                    }
                    if (pathsFilter?.include_event_types.includes(PathType.CustomEvent)) {
                        taxonomicGroupTypes.push(TaxonomicFilterGroupType.CustomEvents)
                    }
                }
                taxonomicGroupTypes.push(TaxonomicFilterGroupType.Wildcards)
                return taxonomicGroupTypes
            },
        ],
    }),
])
