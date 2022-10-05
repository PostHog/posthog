import { kea, key, props, path } from 'kea'

import type { appMetricsSceneLogicType } from './appMetricsSceneLogicType'

export interface AppMetricsLogicProps {
    /** Used as the logic's key */
    pluginConfigId: number
}

export const appMetricsSceneLogic = kea<appMetricsSceneLogicType>([
    path(['scenes', 'apps', 'appMetricsSceneLogic']),
    props({} as AppMetricsLogicProps),
    key((props) => props.pluginConfigId),
])
