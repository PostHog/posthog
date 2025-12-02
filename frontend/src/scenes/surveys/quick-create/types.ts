import { FeatureFlagType } from '~/types'

export type QuickSurveyContext = {
    type: QuickSurveyType.FEATURE_FLAG
    flag: FeatureFlagType
    initialVariantKey?: string | null
}

export interface QuickSurveyFormProps {
    context: QuickSurveyContext
    info?: string
    onCancel?: () => void
}

export enum QuickSurveyType {
    FEATURE_FLAG = 'feature_flag',
}
