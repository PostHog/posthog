import type { HogSenseRenderMap, KnowledgeEntry } from '~/lib/components/HogSense'

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

export const v1FormRenderMap: HogSenseRenderMap = {
    'above-filters': [
        { ids: FF_DETECTION_GROUPS.PROPERTY_HINTS, display: 'banner', className: 'mt-3 mb-3' },
        { ids: FF_DETECTION_GROUPS.LOCAL_EVAL_WARNINGS, display: 'banner', className: 'mt-3 mb-3' },
    ],
}

export const v1ReadOnlyRenderMap: HogSenseRenderMap = {
    'top-warnings': [{ ids: FF_DETECTION_GROUPS.LOCAL_EVAL_WARNINGS, display: 'banner' }],
}

export const v2FormRenderMap: HogSenseRenderMap = {
    'above-filters': [
        { ids: FF_DETECTION_GROUPS.PROPERTY_HINTS, display: 'hint' },
        { ids: FF_DETECTION_GROUPS.LOCAL_EVAL_WARNINGS, display: 'hint' },
    ],
}

const LOCAL_EVAL_DOCS = [
    {
        label: 'Learn more',
        url: 'https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation',
    },
]

export const featureFlagKnowledge: Record<string, KnowledgeEntry> = {
    [FF_DETECTION.NON_INSTANT_PROPERTIES]: {
        summary: 'Flag will evaluate to false on first load',
        description:
            'On the web, this flag will evaluate to false until you send an event and person properties are set.',
        docs: [
            {
                label: 'onFeatureFlags()',
                url: 'https://posthog.com/docs/feature-flags/adding-feature-flag-code#ensuring-flags-are-loaded-before-usage',
                mono: true,
            },
            {
                label: 'bootstrapping',
                url: 'https://posthog.com/docs/feature-flags/bootstrapping',
            },
            {
                label: 'property overrides',
                url: 'https://posthog.com/docs/feature-flags/property-overrides',
            },
        ],
    },
    [FF_DETECTION.IS_NOT_SET_OPERATOR]: {
        summary: 'is_not_set operator',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: is_not_set operator. The flag will still evaluate correctly when not using local evaluation.',
        docs: LOCAL_EVAL_DOCS,
    },
    [FF_DETECTION.STATIC_COHORT]: {
        summary: 'Static cohorts',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: static cohorts. The flag will still evaluate correctly when not using local evaluation.',
        docs: LOCAL_EVAL_DOCS,
    },
    [FF_DETECTION.REGEX_LOOKAHEAD]: {
        summary: 'Lookahead in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: lookahead in regex. The flag will still evaluate correctly when not using local evaluation.',
        docs: LOCAL_EVAL_DOCS,
    },
    [FF_DETECTION.REGEX_LOOKBEHIND]: {
        summary: 'Lookbehind in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: lookbehind in regex. The flag will still evaluate correctly when not using local evaluation.',
        docs: LOCAL_EVAL_DOCS,
    },
    [FF_DETECTION.REGEX_BACKREFERENCES]: {
        summary: 'Backreferences in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: backreferences in regex. The flag will still evaluate correctly when not using local evaluation.',
        docs: LOCAL_EVAL_DOCS,
    },
}
