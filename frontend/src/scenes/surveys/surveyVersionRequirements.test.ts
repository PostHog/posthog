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
})
