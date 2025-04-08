import { connect, kea, key, path, props, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { PathsLink, PathsV2Item } from '~/queries/schema/schema-general'
import { isPathsV2Query } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { pathsV2DataLogicType } from './pathsV2DataLogicType'
import { PathNodeType, Paths } from './types'

export const DEFAULT_STEP_LIMIT = 5

const DEFAULT_PATH_LOGIC_KEY = 'default_path_key'

/** Convert results to the v1 format, so that I don't have to rewrite the frontend immmediately. */
const convertToLegacyPaths = (results: PathsV2Item[]): PathsLink[] => {
    return results.map(({ value, source_step, target_step, step_index }) => ({
        source: step_index + '_' + source_step,
        target: step_index + 1 + '_' + target_step,
        value,
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
            [
                'insightQuery',
                'insightData',
                'insightDataLoading',
                'insightDataError',
                'pathsV2Filter',
                'theme',
                'querySource',
            ],
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
                const uniqueNodeNames = new Set(results.flatMap((link) => [link.source, link.target]))

                const nodes = Array.from(uniqueNodeNames).map((nodeName) => ({
                    name: nodeName,
                    type: nodeName.includes('$$__posthog_dropoff__$$')
                        ? PathNodeType.Dropoff
                        : nodeName.includes('$$__posthog_other__$$')
                        ? PathNodeType.Other
                        : PathNodeType.Node,
                    step_index: parseInt(nodeName.split('_')[0], 10),
                }))

                return {
                    nodes,
                    links: results,
                }
            },
        ],
    }),
])
