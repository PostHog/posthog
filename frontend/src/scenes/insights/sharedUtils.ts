// This is separate from utils.ts because here we don't include `funnelLogic`, `retentionTableLogic`, etc

import { InsightLogicProps } from '~/types'

/**
 * Get a key function for InsightLogicProps.
 * The key will equals either 'scene', 'new' or an ID.
 *
 * @param defaultKey
 * @param sceneKey
 */
export const keyForInsightLogicProps =
    (defaultKey = 'new', sceneKey = 'scene') =>
    (props: InsightLogicProps): string | number => {
        if (!('dashboardItemId' in props)) {
            throw new Error('Must init with dashboardItemId, even if undefined')
        }
        return props.syncWithUrl ? sceneKey : props.dashboardItemId || defaultKey
    }
