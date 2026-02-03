import { compareVersion } from 'lib/utils/semver'

import {
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    Survey,
    SurveyMatchType,
    SurveyPosition,
    SurveyQuestionType,
    SurveySchedule,
    SurveyTabPosition,
} from '~/types'

import { SURVEY_RATING_SCALE } from './constants'

export type SurveySdkType =
    | 'posthog-js'
    | 'posthog-react-native'
    | 'posthog-ios'
    | 'posthog-android'
    | 'posthog_flutter'

export type SdkVersionRequirements = Partial<Record<SurveySdkType, string>>

export type UnsupportedSdk = {
    sdk: SurveySdkType
    issue: `https://github.com/${string}` | false
}

export type SurveyFeatureRequirement = {
    check: (survey: Survey) => boolean
    sdkVersions: SdkVersionRequirements
    feature: string
    docsUrl?: string
    unsupportedSdks: UnsupportedSdk[]
}

/**
 * sorry this is kinda annoying but we are not doing a good job of feature
 * parity across SDKs, it's getting difficult to keep track of, and it's
 * frustrating to users.
 *
 * every entry here in SURVEY_SDK_REQUIREMENTS is validated via unit test
 * (./surveyVersionRequirements.test.ts) to contain every possible SDK
 * (SurveySdkType) in either the sdkVersions or unsupportedSdks.
 *
 * each entry in unsupportedSdks must also have an associated gh issue/PR
 * OR be explicitly marked as `issue: false`, meaning we will not implement
 * (e.g. for HTML rendering in mobile)
 *
 * user-facing warnings for unsupported SDKs say "not supported" if `issue` is
 * false, or "not yet supported" + a link to the GH issue if it exists.
 *
 * if you add a new feature, or need to update an existing one, you can
 * use the claude skill `/survey-sdk-audit "feature name"` to help verify
 * compatibility across all SDKs, create github issues, and update this list.
 */
export const SURVEY_SDK_REQUIREMENTS: SurveyFeatureRequirement[] = [
    {
        feature: 'URL targeting with regex',
        sdkVersions: { 'posthog-js': '1.82.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: false },
            { sdk: 'posthog-ios', issue: false },
            { sdk: 'posthog-android', issue: false },
            { sdk: 'posthog_flutter', issue: false },
        ],
        check: (s) => !!s.conditions?.url && s.conditions?.urlMatchType === SurveyMatchType.Regex,
    },
    {
        feature: 'URL targeting with exact match',
        sdkVersions: { 'posthog-js': '1.82.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: false },
            { sdk: 'posthog-ios', issue: false },
            { sdk: 'posthog-android', issue: false },
            { sdk: 'posthog_flutter', issue: false },
        ],
        check: (s) => !!s.conditions?.url && s.conditions?.urlMatchType === SurveyMatchType.Exact,
    },
    {
        feature: 'Device types targeting',
        sdkVersions: {
            'posthog-js': '1.214.0',
            'posthog-react-native': '4.3.0',
            'posthog-ios': '3.22.0',
            'posthog-android': '3.21.0',
            posthog_flutter: '5.1.0', // delegate; first version to require posthog-ios >= 3.22
        },
        unsupportedSdks: [],
        check: (s) => (s.conditions?.deviceTypes?.length ?? 0) > 0,
    },
    {
        feature: 'Custom font selection',
        sdkVersions: {
            'posthog-js': '1.223.4',
            'posthog-ios': '3.22.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog-android', issue: false }, // delegate pattern - no built-in UI
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2959' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/258' },
        ],
        check: (s) => s.appearance?.fontFamily !== undefined && s.appearance?.fontFamily !== 'inherit',
    },
    {
        feature: 'Repeated survey activation (show every time)',
        sdkVersions: { 'posthog-js': '1.234.11' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2961' },
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/446' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/389' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/260' },
        ],
        check: (s) => s.schedule === SurveySchedule.Always,
    },
    {
        feature: 'Feedback button surveys',
        sdkVersions: { 'posthog-js': '1.294.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: false },
            { sdk: 'posthog-ios', issue: false },
            { sdk: 'posthog-android', issue: false },
            { sdk: 'posthog_flutter', issue: false },
        ],
        check: (s) =>
            s.appearance?.position === SurveyPosition.NextToTrigger ||
            (s.appearance?.tabPosition !== undefined && s.appearance?.tabPosition !== SurveyTabPosition.Right),
    },
    {
        feature: 'Partial response collection',
        sdkVersions: { 'posthog-js': '1.240.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2962' },
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/447' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/390' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/261' },
        ],
        check: (s) => s.enable_partial_responses === true,
    },
    {
        feature: 'Auto-submit on selection',
        sdkVersions: { 'posthog-js': '1.244.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2963' },
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/448' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/391' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/262' },
        ],
        check: (s) =>
            s.questions.some(
                (q) =>
                    (q.type === SurveyQuestionType.SingleChoice ||
                        q.type === SurveyQuestionType.MultipleChoice ||
                        q.type === SurveyQuestionType.Rating) &&
                    (q as MultipleSurveyQuestion | RatingSurveyQuestion).skipSubmitButton === true
            ),
    },
    {
        feature: 'Link to specific feature flag variant',
        sdkVersions: {
            'posthog-js': '1.259.0',
            'posthog-react-native': '4.4.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/445' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/388' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/259' },
        ],
        check: (s) => !!s.conditions?.linkedFlagVariant,
    },
    {
        feature: 'Event trigger property filters',
        sdkVersions: { 'posthog-js': '1.268.0', 'posthog-react-native': '4.16.0' },
        unsupportedSdks: [
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/449' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/392' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/263' },
        ],
        check: (s) =>
            (s.conditions?.events?.values?.length ?? 0) > 0 &&
            !!s.conditions?.events?.values?.some((e) => Object.keys(e.propertyFilters ?? {}).length > 0),
    },
    {
        feature: 'Cancellation events',
        sdkVersions: { 'posthog-js': '1.299.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2964' },
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/450' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/393' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/264' },
        ],
        check: (s) => (s.conditions?.cancelEvents?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Targeting with actions',
        sdkVersions: { 'posthog-js': '1.301.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2965' },
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/451' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/394' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/265' },
        ],
        check: (s) => (s.conditions?.actions?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Styling input appearance',
        sdkVersions: {
            'posthog-js': '1.300.0',
            'posthog-react-native': '4.15.0',
            'posthog-ios': '3.38.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog-android', issue: false }, // delegate pattern - no built-in UI
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/pull/233' },
        ],
        check: (s) => s.appearance?.inputBackground !== undefined || s.appearance?.inputTextColor !== undefined,
    },
    {
        feature: 'Custom text colors',
        sdkVersions: {
            'posthog-js': '1.310.1',
            'posthog-react-native': '4.17.0',
            'posthog-ios': '3.38.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog-android', issue: false }, // delegate pattern - no built-in UI
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/pull/233' },
        ],
        check: (s) => s.appearance?.textColor !== undefined || s.appearance?.submitButtonTextColor !== undefined,
    },
    {
        feature: 'Thumbs up/down question',
        sdkVersions: {
            'posthog-js': '1.326.0',
            'posthog-react-native': '4.19.0',
            'posthog-ios': '3.38.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/pull/233' },
            { sdk: 'posthog-android', issue: false }, // delegate pattern - no built-in UI
        ],
        check: (s) =>
            s.questions.some(
                (q) => q.type === SurveyQuestionType.Rating && q.scale === SURVEY_RATING_SCALE.THUMB_2_POINT
            ),
    },
]

export function meetsVersionRequirement(version: string | null | undefined, minVersion: string): boolean {
    if (!version) {
        return true
    }
    try {
        return compareVersion(version, minVersion) >= 0
    } catch {
        return true
    }
}

export type TeamSdkVersions = Partial<Record<SurveySdkType, string | null>>

export type SurveyFeatureWarning = {
    feature: string
    versionIssues: { sdkType: SurveySdkType; currentVersion: string; minVersion: string }[]
    unsupportedSdks: UnsupportedSdk[]
}

export function getSurveyWarnings(survey: Survey, teamSdkVersions: TeamSdkVersions): SurveyFeatureWarning[] {
    const warnings: SurveyFeatureWarning[] = []
    const activeTeamSdkTypes = Object.keys(teamSdkVersions) as SurveySdkType[]

    for (const req of SURVEY_SDK_REQUIREMENTS) {
        if (!req.check(survey)) {
            continue
        }

        const versionIssues: SurveyFeatureWarning['versionIssues'] = []
        const unsupportedSdks: UnsupportedSdk[] = []

        for (const [sdkType, minVersion] of Object.entries(req.sdkVersions) as [SurveySdkType, string][]) {
            const teamVersion = teamSdkVersions[sdkType]
            if (teamVersion && !meetsVersionRequirement(teamVersion, minVersion)) {
                versionIssues.push({ sdkType, currentVersion: teamVersion, minVersion })
            }
        }

        if (req.unsupportedSdks) {
            for (const sdk of req.unsupportedSdks) {
                if (activeTeamSdkTypes.includes(sdk.sdk)) {
                    unsupportedSdks.push(sdk)
                }
            }
        }

        if (versionIssues.length > 0 || unsupportedSdks.length > 0) {
            warnings.push({ feature: req.feature, versionIssues, unsupportedSdks })
        }
    }

    return warnings
}
