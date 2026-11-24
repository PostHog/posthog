import { compareVersion } from 'lib/utils/semver'

import {
    BasicSurveyQuestion,
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
import { isIntroScreenShown } from './surveyIntroScreen'

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
    /** Printed under the generated SDK feature support table, for requirements a version number can't express. */
    docsNotes?: string[]
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
            'posthog-ios': '4.0.6',
            'posthog-android': '4.0.3', // via posthog-android-surveys-compose UI module 1.1.0
            posthog_flutter: '5.56.0',
        },
        unsupportedSdks: [{ sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2959' }],
        docsNotes: [
            'Android applies the survey font from `posthog-android-surveys-compose` 1.1.0. Earlier versions of the module ignore it, including those that run with `posthog-android` 4.0.3.',
        ],
        check: (s) => s.appearance?.fontFamily !== undefined && s.appearance?.fontFamily !== 'inherit',
    },
    {
        feature: 'Repeated survey activation (show every time)',
        sdkVersions: {
            'posthog-js': '1.234.11',
            'posthog-react-native': '4.27.0',
            'posthog-ios': '3.43.0',
            'posthog-android': '3.35.0',
            posthog_flutter: '5.18.0',
        },
        unsupportedSdks: [],
        check: (s) => s.schedule === SurveySchedule.Always,
    },
    {
        feature: 'Intro screen',
        sdkVersions: {
            'posthog-js': '1.415.0',
            'posthog-react-native': '4.63.0',
            'posthog-ios': '3.70.0',
            'posthog-android': '3.61.0',
            posthog_flutter: '5.39.0',
        },
        unsupportedSdks: [],
        check: (s) => isIntroScreenShown(s.appearance),
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
        feature: 'Custom survey position',
        sdkVersions: {
            'posthog-js': '1.245.0',
            'posthog-react-native': '4.43.13',
            'posthog-ios': '3.95.0',
        },
        unsupportedSdks: [
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/502' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/379' },
        ],
        // True when a non-default popover position is set. NextToTrigger is excluded
        // here because it is covered by the "Feedback button surveys" entry above.
        check: (s) =>
            s.appearance?.position !== undefined &&
            s.appearance?.position !== SurveyPosition.Right &&
            s.appearance?.position !== SurveyPosition.NextToTrigger,
    },
    {
        feature: 'Partial response collection',
        sdkVersions: {
            'posthog-js': '1.240.0',
            'posthog-ios': '3.79.0',
            'posthog-android': '3.70.0',
            posthog_flutter: '5.48.0',
            'posthog-react-native': '4.75.0',
        },
        unsupportedSdks: [],
        check: (s) => s.enable_partial_responses === true,
    },
    {
        feature: 'Auto-submit on selection',
        sdkVersions: {
            'posthog-js': '1.244.0',
            'posthog-react-native': '4.26.0',
            'posthog-ios': '3.77.0',
            'posthog-android': '3.66.4', // via posthog-android-surveys-compose UI module 0.3.0
            posthog_flutter: '5.45.0',
        },
        unsupportedSdks: [],
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
            'posthog-ios': '3.78.0',
            'posthog-android': '3.67.0',
            posthog_flutter: '5.47.0', // first version to require posthog-ios >= 3.80.0 and posthog-android >= 3.69.0
        },
        unsupportedSdks: [],
        check: (s) => !!s.conditions?.linkedFlagVariant,
    },
    {
        feature: 'Event trigger property filters',
        sdkVersions: {
            'posthog-js': '1.268.0',
            'posthog-react-native': '4.16.0',
            'posthog-android': '3.38.0',
            'posthog-ios': '3.47.0',
            posthog_flutter: '5.20.0',
        },
        unsupportedSdks: [],
        check: (s) =>
            (s.conditions?.events?.values?.length ?? 0) > 0 &&
            !!s.conditions?.events?.values?.some((e) => Object.keys(e.propertyFilters ?? {}).length > 0),
    },
    {
        // No SDK survey matcher implements gte or lte, so a stored filter with either operator never matches.
        feature: 'Event filters using ≥ or ≤',
        sdkVersions: {},
        unsupportedSdks: [
            { sdk: 'posthog-js', issue: false },
            { sdk: 'posthog-react-native', issue: false },
            { sdk: 'posthog-ios', issue: false },
            { sdk: 'posthog-android', issue: false },
            { sdk: 'posthog_flutter', issue: false },
        ],
        check: (s) =>
            [...(s.conditions?.events?.values ?? []), ...(s.conditions?.cancelEvents?.values ?? [])].some((e) =>
                Object.values(e.propertyFilters ?? {}).some((filter) =>
                    (['gte', 'lte'] as string[]).includes(filter.operator)
                )
            ),
    },
    {
        feature: 'Cancellation events',
        sdkVersions: { 'posthog-js': '1.299.0', 'posthog-ios': '3.96.0' },
        unsupportedSdks: [
            { sdk: 'posthog-react-native', issue: 'https://github.com/PostHog/posthog-js/issues/2964' },
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
            'posthog-android': '3.49.0', // via posthog-android-surveys-compose UI module
            posthog_flutter: '5.13.0',
        },
        unsupportedSdks: [],
        check: (s) => s.appearance?.inputBackground !== undefined || s.appearance?.inputTextColor !== undefined,
    },
    {
        feature: 'Custom text colors',
        sdkVersions: {
            'posthog-js': '1.310.1',
            'posthog-react-native': '4.17.0',
            'posthog-ios': '3.38.0',
            'posthog-android': '3.49.0', // via posthog-android-surveys-compose UI module
            posthog_flutter: '5.13.0',
        },
        unsupportedSdks: [],
        check: (s) => s.appearance?.textColor !== undefined || s.appearance?.submitButtonTextColor !== undefined,
    },
    {
        feature: 'Thumbs up/down question',
        sdkVersions: {
            'posthog-js': '1.326.0',
            'posthog-react-native': '4.19.0',
            'posthog-ios': '3.38.0',
            'posthog-android': '3.49.0', // via posthog-android-surveys-compose UI module
            posthog_flutter: '5.13.0',
        },
        unsupportedSdks: [],
        check: (s) =>
            s.questions.some(
                (q) => q.type === SurveyQuestionType.Rating && q.scale === SURVEY_RATING_SCALE.THUMB_2_POINT
            ),
    },
    {
        feature: 'Shuffle questions',
        sdkVersions: { 'posthog-js': '1.131.5', 'posthog-react-native': '4.68.0' },
        unsupportedSdks: [
            { sdk: 'posthog-ios', issue: 'https://github.com/PostHog/posthog-ios/issues/492' },
            { sdk: 'posthog-android', issue: 'https://github.com/PostHog/posthog-android/issues/442' },
            { sdk: 'posthog_flutter', issue: 'https://github.com/PostHog/posthog-flutter/issues/310' },
        ],
        check: (s) => s.appearance?.shuffleQuestions === true,
    },
    {
        feature: 'Shuffle choice options',
        sdkVersions: {
            'posthog-js': '1.131.5',
            'posthog-react-native': '4.77.1', // 4.68.0-4.77.0 shuffled choices but submitted the wrong option
            'posthog-ios': '3.76.0',
            'posthog-android': '3.66.0', // via posthog-android-surveys-compose UI module 0.2.2
            posthog_flutter: '5.44.1',
        },
        unsupportedSdks: [],
        check: (s) =>
            s.questions.some(
                (q) =>
                    (q.type === SurveyQuestionType.SingleChoice || q.type === SurveyQuestionType.MultipleChoice) &&
                    (q as MultipleSurveyQuestion).shuffleOptions === true
            ),
    },
    {
        feature: 'Survey wait period',
        sdkVersions: {
            'posthog-js': '1.105.7',
            'posthog-react-native': '4.81.5',
            'posthog-ios': '3.44.0',
            'posthog-android': '3.35.0',
            posthog_flutter: '5.18.0',
        },
        unsupportedSdks: [],
        check: (s) => (s.conditions?.seenSurveyWaitPeriodInDays ?? 0) > 0,
    },
    {
        feature: 'Delay survey popup',
        sdkVersions: {
            'posthog-js': '1.141.0',
            'posthog-ios': '3.54.0',
            'posthog-android': '3.49.0',
            'posthog-react-native': '4.85.0',
            posthog_flutter: '5.54.0',
        },
        unsupportedSdks: [],
        check: (s) => (s.appearance?.surveyPopupDelaySeconds ?? 0) > 0,
    },
    {
        feature: 'Response length validation',
        sdkVersions: { 'posthog-js': '1.344.0', 'posthog-react-native': '4.31.0' },
        unsupportedSdks: [
            { sdk: 'posthog-ios', issue: false },
            { sdk: 'posthog-android', issue: false },
            { sdk: 'posthog_flutter', issue: false },
        ],
        check: (s) =>
            s.questions.some(
                (q) =>
                    q.type === SurveyQuestionType.Open &&
                    (q as BasicSurveyQuestion).validation &&
                    (q as BasicSurveyQuestion).validation!.length > 0
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
