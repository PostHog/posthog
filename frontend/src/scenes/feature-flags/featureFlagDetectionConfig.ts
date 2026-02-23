export const FF_DETECTION = {
    NON_INSTANT_PROPERTIES: 'non-instant-properties',
    IS_NOT_SET_OPERATOR: 'is-not-set-operator',
    STATIC_COHORT: 'static-cohort',
    REGEX_LOOKAHEAD: 'regex-lookahead',
    REGEX_LOOKBEHIND: 'regex-lookbehind',
    REGEX_BACKREFERENCES: 'regex-backreferences',
} as const

export const FF_DETECTION_GROUPS = {
    PROPERTY_HINTS: [FF_DETECTION.NON_INSTANT_PROPERTIES],
    LOCAL_EVAL_WARNINGS: [
        FF_DETECTION.IS_NOT_SET_OPERATOR,
        FF_DETECTION.STATIC_COHORT,
        FF_DETECTION.REGEX_LOOKAHEAD,
        FF_DETECTION.REGEX_LOOKBEHIND,
        FF_DETECTION.REGEX_BACKREFERENCES,
    ],
} as const
