import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { performQuery } from '~/queries/query'
import { PathsLink, PathsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import type { funnelPathsExpansionLogicType } from './funnelPathsExpansionLogicType'
import { buildPathsQuery, PathExpansion, pathExpansionCacheKey } from './pathFlowUtils'

const DEFAULT_LOGIC_KEY = 'default_funnel_paths_expansion'

export const funnelPathsExpansionLogic = kea<funnelPathsExpansionLogicType>([
    path((key) => ['scenes', 'funnels', 'FunnelFlowGraph', 'funnelPathsExpansionLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [funnelDataLogic(props), ['querySource']],
    })),

    actions({
        expandPath: (expansion: PathExpansion) => ({ expansion }),
        collapsePath: true,
        setPathsResults: (cacheKey: string, results: PathsLink[]) => ({ cacheKey, results }),
    }),

    reducers({
        expandedPath: [
            null as PathExpansion | null,
            {
                expandPath: (_, { expansion }) => expansion,
                collapsePath: () => null,
            },
        ],
        pathsResultsCache: [
            {} as Record<string, PathsLink[]>,
            {
                setPathsResults: (state, { cacheKey, results }) => ({ ...state, [cacheKey]: results }),
            },
        ],
        pathsLoading: [
            false,
            {
                expandPath: () => true,
                setPathsResults: () => false,
                collapsePath: () => false,
            },
        ],
    }),

    selectors({
        expandedPathCacheKey: [
            (s) => [s.expandedPath],
            (expandedPath): string | null => (expandedPath ? pathExpansionCacheKey(expandedPath) : null),
        ],
        expandedPathResults: [
            (s) => [s.expandedPathCacheKey, s.pathsResultsCache],
            (cacheKey, pathsResultsCache): PathsLink[] | null =>
                cacheKey ? (pathsResultsCache[cacheKey] ?? null) : null,
        ],
    }),

    listeners(({ actions, values }) => ({
        expandPath: async ({ expansion }, breakpoint) => {
            if (values.expandedPathCacheKey && values.expandedPathResults) {
                actions.setPathsResults(values.expandedPathCacheKey, values.expandedPathResults)
                return
            }

            const { querySource } = values
            if (!querySource || querySource.aggregation_group_type_index != undefined) {
                actions.collapsePath()
                lemonToast.info('Cannot expand paths for group aggregation')
                return
            }

            const query = buildPathsQuery(expansion, querySource)
            try {
                const response = await performQuery<PathsQuery>(query, undefined, 'blocking')
                breakpoint()
                const results = (response?.results ?? []) as PathsLink[]
                if (results.length === 0) {
                    actions.collapsePath()
                    lemonToast.info('Path expansion returned no results')
                } else {
                    actions.setPathsResults(values.expandedPathCacheKey!, results)
                }
            } catch {
                breakpoint()
                lemonToast.error('An error occurres when expanding paths')
                actions.collapsePath()
            }
        },
    })),
])
