import { Experiment, FeatureFlagType } from '~/types'

import { FunnelContext } from '../utils/opportunityDetection'

export type QuickSurveyContext =
    | { type: QuickSurveyType.FEATURE_FLAG; flag: FeatureFlagType; initialVariantKey?: string | null }
    | { type: QuickSurveyType.FUNNEL; funnel: FunnelContext }
    | { type: QuickSurveyType.EXPERIMENT; experiment: Experiment }
    | { type: QuickSurveyType.ANNOUNCEMENT }
    | { type: QuickSurveyType.COHORT; cohortId: number; cohortName?: string }

export interface QuickSurveyFormProps {
    context: QuickSurveyContext
    info?: string
    onCancel?: () => void
}

export enum QuickSurveyType {
    FEATURE_FLAG = 'feature_flag',
    FUNNEL = 'funnel',
    EXPERIMENT = 'experiment',
    ANNOUNCEMENT = 'announcement',
    COHORT = 'cohort',
}
