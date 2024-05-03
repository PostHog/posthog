import { kea, path } from 'kea'

import type { heatmapsSceneLogicType } from './heatmapsSceneLogicType'

export const heatmapsSceneLogic = kea<heatmapsSceneLogicType>([path(['scenes', 'heatmaps', 'heatmapsSceneLogic'])])
