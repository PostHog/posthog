import { kea, key, path, props } from 'kea'

import type { featureLogicType } from './featureLogicType'

export interface FeatureLogicProps {
    /** Either a UUID or "new". */
    id: string
}

export const featureLogic = kea<featureLogicType>([
    path(['scenes', 'features', 'featureLogic']),
    props({} as FeatureLogicProps),
    key(({ id }) => id),
])
