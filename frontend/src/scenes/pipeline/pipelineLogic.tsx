import { kea } from 'kea'
import type { pipelineLogicType } from './pipelineLogicType'

export const pipelineLogic = kea<pipelineLogicType>({
    path: ['scenes', 'pipeline', 'pipelineLogic'],
})
