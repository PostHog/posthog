import { connect, kea, key, path, props, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { PathsLink, PathsV2Item } from '~/queries/schema/schema-general'
import { isPathsV2Query } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { pathsV2DataLogicType } from './pathsV2DataLogicType'
import { Paths, PathsNode } from './types'

export const DEFAULT_STEP_LIMIT = 5

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

/** Convert results to the v1 format, so that I don't have to rewrite the frontend immmediately. */
const convertToLegacyPaths = (results: PathsV2Item[]): PathsLink[] => {
    return results.map(({ event_count, source_step, target_step, step_index }) => ({
        source: step_index + '_' + source_step,
        target: step_index + 1 + '_' + target_step,
        value: event_count,
        average_conversion_time: 0,
    }))
}

export const pathsV2DataLogic = kea<pathsV2DataLogicType>([
    path((key) => ['scenes', 'paths', 'pathsV2DataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_PATH_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightQuery', 'insightData', 'insightDataLoading', 'insightDataError', 'pathsV2Filter', 'theme'],
        ],
        actions: [insightVizDataLogic(props), ['updateInsightFilter', 'updateQuerySource']],
    })),

    selectors({
        results: [
            (s) => [s.insightQuery, s.insightData],
            (insightQuery, insightData): Paths[] => {
                return isPathsV2Query(insightQuery) ? convertToLegacyPaths(insightData?.result) ?? [] : []
            },
        ],
        paths: [
            (s) => [s.results],
            (results): Paths => {
                const nodes: Record<string, PathsNode> = {}

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
    }),
])
