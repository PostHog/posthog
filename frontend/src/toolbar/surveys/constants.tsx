import { SurveyType } from '~/types'

export const SURVEY_TYPE_LABELS: Record<SurveyType, string> = {
    [SurveyType.Popover]: 'Popover',
    [SurveyType.Widget]: 'Widget',
    [SurveyType.FullScreen]: 'Full screen',
    [SurveyType.API]: 'API',
    [SurveyType.ExternalSurvey]: 'External',
}

export const STATUS_COLORS: Record<string, 'primary' | 'muted' | 'danger'> = {
    active: 'primary',
    draft: 'muted',
    complete: 'muted',
}

export const SIDEBAR_WIDTH = 380
