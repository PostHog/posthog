import { Survey, SurveyEventsWithProperties } from '~/types'

import { SURVEY_SDK_REQUIREMENTS, SurveySdkType, getSurveyWarnings } from './surveyVersionRequirements'

const ALL_SDK_TYPES: SurveySdkType[] = [
    'posthog-js',
    'posthog-react-native',
    'posthog-ios',
    'posthog-android',
    'posthog_flutter',
]

describe('SURVEY_SDK_REQUIREMENTS', () => {
    it.each(SURVEY_SDK_REQUIREMENTS.map((req) => [req.feature, req]))(
        '"%s" must cover all SDK types in sdkVersions + unsupportedSdks',
        (_, requirement) => {
            const coveredByVersions = Object.keys(requirement.sdkVersions) as SurveySdkType[]
            const coveredByUnsupported = (requirement.unsupportedSdks ?? []).map((u) => u.sdk)
            const allCovered = new Set([...coveredByVersions, ...coveredByUnsupported])

            const missing = ALL_SDK_TYPES.filter((sdk) => !allCovered.has(sdk))

            expect(missing).toEqual([])
        }
    )

    it.each([
        { field: 'events', operator: 'gte', warns: true },
        { field: 'cancelEvents', operator: 'lte', warns: true },
        { field: 'events', operator: 'gt', warns: false },
    ] as const)('warns about $operator filters on $field: $warns', ({ field, operator, warns }) => {
        const triggerEvent = {
            name: 'checkout completed',
            propertyFilters: { order_total: { values: ['100'], operator } },
        } as unknown as SurveyEventsWithProperties
        const survey = { questions: [], conditions: { [field]: { values: [triggerEvent] } } } as unknown as Survey

        const features = getSurveyWarnings(survey, { 'posthog-js': '1.400.0' }).map((w) => w.feature)

        expect(features.includes('Event filters using ≥ or ≤')).toBe(warns)
    })

    it.each([
        ['a URL condition', { url: '/order-confirmed' }, '4.10.4', ['posthog-react-native'], []],
        ['a CSS selector condition', { selector: '#checkout' }, '4.10.4', ['posthog-react-native'], []],
        ['an SDK that predates the URL skip', { url: '/order-confirmed' }, '4.10.3', [], ['posthog-react-native']],
        ['no URL or selector condition', {}, '4.10.4', [], ['posthog-react-native']],
    ])(
        'hides gaps of SDKs that skip the survey, for %s',
        (_name, urlConditions, reactNativeVersion, expectedSkipping, expectedUnsupported) => {
            const survey = {
                questions: [],
                enable_partial_responses: true,
                conditions: { ...urlConditions, seenSurveyWaitPeriodInDays: 7 },
            } as unknown as Survey

            const warnings = getSurveyWarnings(survey, {
                'posthog-js': '1.400.0',
                'posthog-react-native': reactNativeVersion,
            })

            expect(warnings.flatMap((w) => w.skippingSdks)).toEqual(expectedSkipping)
            expect(
                warnings.find((w) => w.feature === 'Survey wait period')?.unsupportedSdks.map((u) => u.sdk) ?? []
            ).toEqual(expectedUnsupported)
        }
    )

    it.each([
        ['an intro that renders', { displayIntroScreen: true, introScreenHeader: 'Welcome' }, true],
        ['an intro with no header or description', { displayIntroScreen: true }, false],
    ])('flags the Intro screen requirement for %s', (_name, appearance, expected) => {
        const requirement = SURVEY_SDK_REQUIREMENTS.find((req) => req.feature === 'Intro screen')

        expect(requirement?.check({ appearance } as Survey)).toBe(expected)
    })
})
