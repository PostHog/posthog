import { kea, path } from 'kea'

import type { errorTrackingSceneLogicType } from './errorTrackingLogicType'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),
])
