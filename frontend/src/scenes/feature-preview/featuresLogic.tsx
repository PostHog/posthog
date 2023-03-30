import { kea } from 'kea'
import { featuresLogicType } from './featuresLogicType'

export const featuresLogic = kea<featuresLogicType>({
    path: ['scenes', 'feature-preview', 'featuresLogic'],
})
