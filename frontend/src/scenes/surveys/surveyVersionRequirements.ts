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
        check: (s) => s.enable_partial_responses === true,
    },
    {
        feature: 'Auto-submit on selection',
        sdkVersions: { 'posthog-js': '1.244.0' },
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
        sdkVersions: { 'posthog-js': '1.268.0' },
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
        check: (s) => (s.conditions?.cancelEvents?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Targeting with actions',
        sdkVersions: { 'posthog-js': '1.299.0' },
        check: (s) => (s.conditions?.actions?.values?.length ?? 0) > 0,
    },
    {
        feature: 'Styling input appearance',
        sdkVersions: { 'posthog-js': '1.300.0' },
        check: (s) => s.appearance?.inputBackground !== undefined || s.appearance?.inputTextColor !== undefined,
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

export type SurveyVersionWarning = {
    feature: string
    sdkType: SurveySdkType
    currentVersion: string
    minVersion: string
    docsUrl?: string
}

export function getSurveyVersionWarnings(survey: Survey, teamSdkVersions: TeamSdkVersions): SurveyVersionWarning[] {
    const warnings: SurveyVersionWarning[] = []

    for (const req of SURVEY_SDK_REQUIREMENTS) {
        if (!req.check(survey)) {
            continue
        }

        for (const [sdkType, minVersion] of Object.entries(req.sdkVersions) as [SurveySdkType, string][]) {
            const teamVersion = teamSdkVersions[sdkType]

            // only warn if we've seen the team use this sdk AND it's outdated
            if (teamVersion && !meetsVersionRequirement(teamVersion, minVersion)) {
                warnings.push({
                    feature: req.feature,
                    sdkType,
                    currentVersion: teamVersion,
                    minVersion,
                    docsUrl: req.docsUrl,
                })
            }
        }
    }

    return warnings
}
