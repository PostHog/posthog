import { Survey } from '~/types'

import { SURVEY_SDK_REQUIREMENTS, SurveySdkType } from './surveyVersionRequirements'

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
        ['an intro that renders', { displayIntroScreen: true, introScreenHeader: 'Welcome' }, true],
        ['an intro with no header or description', { displayIntroScreen: true }, false],
    ])('flags the Intro screen requirement for %s', (_name, appearance, expected) => {
        const requirement = SURVEY_SDK_REQUIREMENTS.find((req) => req.feature === 'Intro screen')

        expect(requirement?.check({ appearance } as Survey)).toBe(expected)
    })
})
