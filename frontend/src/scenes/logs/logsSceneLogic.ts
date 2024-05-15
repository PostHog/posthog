import { kea, path } from 'kea'

import type { logsSceneLogicType } from './logsSceneLogicType'

export const logsSceneLogic = kea<logsSceneLogicType>([path(['scenes', 'logs', 'logsSceneLogic'])])
