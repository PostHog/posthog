import { connect, kea, key, path, props, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { PathsLink, PathsV2Item } from '~/queries/schema/schema-general'
import { isPathsV2Query } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import type { pathsV2DataLogicType } from './pathsV2DataLogicType'
import { PathNodeType, Paths, PathsNode } from './types'

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
                const links = [
                    { source: '1_a1', target: '2_b1', value: 4 },
                    { source: '1_a1', target: '2_b2', value: 3 },
                    { source: '1_a2', target: '2_$$__posthog_dropoff__$$', value: 2 },
                    { source: '1_a3', target: '2_$$__posthog_step_other__$$', value: 1 },
                    { source: '1_$$__posthog_step_other__$$', target: '2_b1', value: 1 },
                    { source: '1_$$__posthog_step_other__$$', target: '2_$$__posthog_dropoff__$$', value: 4 },
                ]

                const uniqueNodeNames = new Set(links.flatMap((link) => [link.source, link.target]))

                const nodes = Array.from(uniqueNodeNames).map((nodeName) => ({
                    name: nodeName,
                    type: nodeName.includes('$$__posthog_dropoff__$$')
                        ? PathNodeType.Dropoff
                        : nodeName.includes('$$__posthog_step_other__$$')
                        ? PathNodeType.Other
                        : PathNodeType.Node,
                    step_index: parseInt(nodeName.split('_')[0], 10),
                }))

                return { nodes, links }

                // return {
                //     nodes: [
                //         { name: '1_a1', type: PathNodeType.Node, step_index: 1 },
                //         { name: '1_a2', type: PathNodeType.Node, step_index: 1 },
                //         { name: '1_a3', type: PathNodeType.Node, step_index: 1 },
                //         { name: '1_$$__posthog_step_other__$$', type: PathNodeType.Other, step_index: 1 },
                //         { name: '2_b1', type: PathNodeType.Node, step_index: 2 },
                //         { name: '2_b2', type: PathNodeType.Node, step_index: 2 },
                //         { name: '2_$$__posthog_step_other__$$', type: PathNodeType.Other, step_index: 2 },
                //         { name: '2_$$__posthog_dropoff__$$', type: PathNodeType.Dropoff, step_index: 2 },
                //     ],
                //     links: [
                //         { source: '1_a1', target: '2_b1', value: 4 },
                //         { source: '1_a1', target: '2_b2', value: 3 },
                //         { source: '1_a2', target: '2_$$__posthog_dropoff__$$', value: 2 },
                //         { source: '1_a3', target: '2_$$__posthog_step_other__$$', value: 1 },
                //         { source: '1_$$__posthog_step_other__$$', target: '2_b1', value: 1 },
                //         { source: '1_$$__posthog_step_other__$$', target: '2_$$__posthog_dropoff__$$', value: 4 },
                //     ],
                // }

                //                 links: [
                //   {source: 'a1', target: 'b1', value: 4},
                //   {source: 'a1', target: 'b2', value: 3},
                //   {source: 'a2', target: '$$__posthog_dropoff__$$', value: 2},
                //   {source: 'a3', target: '$$__posthog_step_other__$$', value: 1},
                //   {source: '$$__posthog_step_other__$$', target: 'b1', value: 1},
                //   {source: '$$__posthog_step_other__$$', target: '$$__posthog_dropoff__$$', value: 4},
                // ]

                // const nodes: Record<string, PathsNode> = {}

                // for (const path of results) {
                //     console.debug('path', path)

                //     // if (!path.source.startsWith('1_')) {
                //     if (!nodes[path.source]) {
                //         nodes[path.source] = { name: path.source }
                //     }
                //     if (!nodes[path.target]) {
                //         nodes[path.target] = { name: path.target }
                //     }
                //     // }
                // }

                // return {
                //     nodes: Object.values(nodes),
                //     links: results,
                // }
            },
        ],
    }),
])
