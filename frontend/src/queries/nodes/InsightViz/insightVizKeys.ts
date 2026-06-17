import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

/**
 * Kept apart from InsightViz.tsx so logics can build dataNodeLogic keys without
 * statically importing the InsightViz component graph into their chunk.
 */

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps<any>): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

export const insightVizDataCollectionId = (props: InsightLogicProps<any> | undefined, fallback: string): string => {
    return props?.dataNodeCollectionId ?? props?.dashboardId?.toString() ?? props?.dashboardItemId ?? fallback
}
