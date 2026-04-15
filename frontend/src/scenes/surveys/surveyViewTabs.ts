export const LEGACY_SURVEY_TAB_KEYS = ['results', 'overview', 'notifications', 'history'] as const

export const REDESIGN_SURVEY_TAB_KEYS = ['summary', 'responses', 'history'] as const

export const ALL_SURVEY_VIEW_TABS = [...LEGACY_SURVEY_TAB_KEYS, ...REDESIGN_SURVEY_TAB_KEYS] as const
