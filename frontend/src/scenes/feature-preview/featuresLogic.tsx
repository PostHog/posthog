import { kea } from 'kea'
import type { featuresLogicType } from './featuresLogicType'

export const featuresLogic = kea<featuresLogicType>({
    path: ['scenes', 'feature-preview', 'featuresLogic'],
})
