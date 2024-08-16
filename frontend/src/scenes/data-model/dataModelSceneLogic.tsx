import { kea, path } from 'kea'

import type { dataModelSceneLogicType } from './dataModelSceneLogicType'

export const dataModelSceneLogic = kea<dataModelSceneLogicType>([path(['scenes', 'data-model', 'dataModelSceneLogic'])])
