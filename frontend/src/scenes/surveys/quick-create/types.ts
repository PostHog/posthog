import { FeatureFlagType } from '~/types'

import { FunnelContext } from '../utils/opportunityDetection'

export type QuickSurveyContext =
    | { type: QuickSurveyType.FEATURE_FLAG; flag: FeatureFlagType; initialVariantKey?: string | null }
    | { type: QuickSurveyType.FUNNEL; funnel: FunnelContext }

export interface QuickSurveyFormProps {
    context: QuickSurveyContext
    info?: string
    onCancel?: () => void
}

export enum QuickSurveyType {
    FEATURE_FLAG = 'feature_flag',
    FUNNEL = 'funnel',
}
