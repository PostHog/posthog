import { Experiment, FeatureFlagType } from '~/types'

import { FunnelContext } from '../utils/opportunityDetection'

export type QuickSurveyContext =
    | { type: QuickSurveyType.FEATURE_FLAG; flag: FeatureFlagType; initialVariantKey?: string | null }
    | { type: QuickSurveyType.FUNNEL; funnel: FunnelContext }
    | { type: QuickSurveyType.EXPERIMENT; experiment: Experiment }
    | { type: QuickSurveyType.ANNOUNCEMENT }
    | { type: QuickSurveyType.ERROR_TRACKING; exceptionType: string; exceptionMessage?: string | null }
    | { type: QuickSurveyType.WEB_PATH; path: string }

export interface QuickSurveyFormProps {
    context: QuickSurveyContext
    info?: React.ReactNode
    onCancel?: () => void
    showFollowupToggle?: boolean
}

export enum QuickSurveyType {
    FEATURE_FLAG = 'feature_flag',
    FUNNEL = 'funnel',
    EXPERIMENT = 'experiment',
    ANNOUNCEMENT = 'announcement',
    ERROR_TRACKING = 'error_tracking',
    WEB_PATH = 'web_path',
}
