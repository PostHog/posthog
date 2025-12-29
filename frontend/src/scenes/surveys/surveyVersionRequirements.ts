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
    SurveyType,
} from '~/types'

export type SurveySdkType = 'posthog-js' | 'posthog-react-native' | 'posthog-ios' | 'posthog-android'

export type SdkVersionRequirements = Partial<Record<SurveySdkType, string>>

export type SurveyFeatureRequirement = {
    check: (survey: Survey) => boolean
    sdkVersions: SdkVersionRequirements
    feature: string
    docsUrl?: string
    unsupportedSdks?: SurveySdkType[]
}

// list of survey things that require specific sdk version(s)
// update this if you add a new feature that requires an update to the sdk!!
export const SURVEY_SDK_REQUIREMENTS: SurveyFeatureRequirement[] = [
    {
        feature: 'URL targeting with regex',
        sdkVersions: { 'posthog-js': '1.82.0' },
        check: (s) => s.conditions?.urlMatchType === SurveyMatchType.Regex,
    },
    {
        feature: 'URL targeting with exact match',
        sdkVersions: { 'posthog-js': '1.82.0' },
        check: (s) => s.conditions?.urlMatchType === SurveyMatchType.Exact,
    },
    {
        feature: 'Device types targeting',
        sdkVersions: { 'posthog-js': '1.214.0' },
        check: (s) => (s.conditions?.deviceTypes?.length ?? 0) > 0,
    },
    {
        feature: 'Custom font selection',
        sdkVersions: { 'posthog-js': '1.223.4' },
        check: (s) => s.appearance?.fontFamily !== undefined && s.appearance?.fontFamily !== 'inherit',
    },
    {
        feature: 'Repeated survey activation (show every time)',
        sdkVersions: { 'posthog-js': '1.234.11' },
        check: (s) => s.schedule === SurveySchedule.Always,
    },
    {
        feature: 'Survey position "next to feedback button"',
        sdkVersions: { 'posthog-js': '1.235.2' },
        check: (s) => s.appearance?.position === SurveyPosition.NextToTrigger,
    },
    {
        feature: 'Partial response collection',
        sdkVersions: { 'posthog-js': '1.240.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android', 'posthog-react-native'],
        check: (s) => s.enable_partial_responses === true,
    },
    {
        feature: 'Auto-submit on selection',
        sdkVersions: { 'posthog-js': '1.244.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android', 'posthog-react-native'],
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
        feature: 'External link surveys',
        sdkVersions: { 'posthog-js': '1.258.1' },
        check: (s) => s.type === SurveyType.ExternalSurvey,
    },
    {
        feature: 'Link to specific feature flag variant',
        sdkVersions: {
            'posthog-js': '1.259.0',
            'posthog-react-native': '4.4.0',
        },
        check: (s) => !!s.conditions?.linkedFlagVariant,
    },
    {
        feature: 'Event trigger property filters',
        sdkVersions: { 'posthog-js': '1.268.0', 'posthog-react-native': '4.15.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android'],
        check: (s) =>
            (s.conditions?.events?.values?.length ?? 0) > 0 &&
            !!s.conditions?.events?.values?.some((e) => Object.keys(e.propertyFilters ?? {}).length > 0),
    },
    {
        feature: 'Feedback button position',
        sdkVersions: { 'posthog-js': '1.294.0' },
        check: (s) => s.appearance?.tabPosition !== undefined && s.appearance?.tabPosition !== SurveyTabPosition.Right,
    },
    {
        feature: 'Cancellation events',
        sdkVersions: { 'posthog-js': '1.299.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android', 'posthog-react-native'],
        check: (s) => (s.conditions?.cancelEvents?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Targeting with actions',
        sdkVersions: { 'posthog-js': '1.299.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android', 'posthog-react-native'],
        check: (s) => (s.conditions?.actions?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Styling input appearance',
        sdkVersions: { 'posthog-js': '1.300.0' },
        check: (s) => s.appearance?.inputBackground !== undefined || s.appearance?.inputTextColor !== undefined,
    },
    {
        feature: 'Custom text colors',
        sdkVersions: { 'posthog-js': '1.310.1', 'posthog-react-native': '4.17.0' },
        unsupportedSdks: ['posthog-ios', 'posthog-android'],
        check: (s) =>
            s.appearance?.textColor !== undefined ||
            s.appearance?.inputTextColor !== undefined ||
            s.appearance?.submitButtonTextColor !== undefined,
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
    unsupportedSdks: SurveySdkType[]
}

export function getSurveyWarnings(survey: Survey, teamSdkVersions: TeamSdkVersions): SurveyFeatureWarning[] {
    const warnings: SurveyFeatureWarning[] = []
    const activeTeamSdkTypes = Object.keys(teamSdkVersions) as SurveySdkType[]

    for (const req of SURVEY_SDK_REQUIREMENTS) {
        if (!req.check(survey)) {
            continue
        }

        const versionIssues: SurveyFeatureWarning['versionIssues'] = []
        const unsupportedSdks: SurveySdkType[] = []

        for (const [sdkType, minVersion] of Object.entries(req.sdkVersions) as [SurveySdkType, string][]) {
            const teamVersion = teamSdkVersions[sdkType]
            if (teamVersion && !meetsVersionRequirement(teamVersion, minVersion)) {
                versionIssues.push({ sdkType, currentVersion: teamVersion, minVersion })
            }
        }

        if (req.unsupportedSdks) {
            for (const sdk of req.unsupportedSdks) {
                if (activeTeamSdkTypes.includes(sdk)) {
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
