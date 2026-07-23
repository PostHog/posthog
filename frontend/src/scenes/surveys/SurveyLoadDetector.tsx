import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonSelect, LemonTable } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { StatRow } from 'scenes/surveys/SurveyStatsSummary'
import { urls } from 'scenes/urls'

import type {
    SurveyLoadDetectorOverlapApi,
    SurveyLoadDetectorSurveyApi,
} from 'products/surveys/frontend/generated/api.schemas'

import { surveyLoadDetectorLogic } from './surveyLoadDetectorLogic'

const WINDOW_PRESETS: { value: number; label: string }[] = [
    { value: 15 * 60, label: '15 minutes' },
    { value: 60 * 60, label: '1 hour' },
    { value: 4 * 60 * 60, label: '4 hours' },
    { value: 12 * 60 * 60, label: '12 hours' },
    { value: 24 * 60 * 60, label: '24 hours' },
    { value: 3 * 24 * 60 * 60, label: '3 days' },
    { value: 7 * 24 * 60 * 60, label: '7 days' },
]

const LOOKBACK_PRESETS: { value: number; label: string }[] = [7, 14, 30, 60, 90].map((days) => ({
    value: days,
    label: `Last ${days} days`,
}))

function withCurrentValue(
    presets: { value: number; label: string }[],
    value: number,
    labelForValue: (value: number) => string
): { value: number; label: string }[] {
    if (presets.some((option) => option.value === value)) {
        return presets
    }
    return [...presets, { value, label: labelForValue(value) }].sort((a, b) => a.value - b.value)
}

function SurveyNameCell({ surveyId, surveyName }: { surveyId: string; surveyName: string | null }): JSX.Element {
    if (!surveyName) {
        return <span className="text-secondary italic">Deleted survey</span>
    }
    return <LemonTableLink to={urls.survey(surveyId)} title={surveyName} />
}

export function SurveyLoadDetector(): JSX.Element {
    const { analysis, analysisLoading, config, hasUnsavedChanges, currentTeamLoading } =
        useValues(surveyLoadDetectorLogic)
    const { setConfigValue, saveAsTeamDefault, loadAnalysis } = useActions(surveyLoadDetectorLogic)

    const summary = analysis?.summary

    const overlapColumns: LemonTableColumns<SurveyLoadDetectorOverlapApi> = [
        {
            title: 'Survey',
            key: 'survey_1',
            render: (_, overlap) => (
                <SurveyNameCell surveyId={overlap.survey_id_1} surveyName={overlap.survey_name_1} />
            ),
        },
        {
            title: 'Shown together with',
            key: 'survey_2',
            render: (_, overlap) => (
                <SurveyNameCell surveyId={overlap.survey_id_2} surveyName={overlap.survey_name_2} />
            ),
        },
        {
            title: 'Users affected',
            key: 'users_affected',
            align: 'right',
            render: (_, overlap) => humanFriendlyNumber(overlap.users_affected),
        },
    ]

    const surveyColumns: LemonTableColumns<SurveyLoadDetectorSurveyApi> = [
        {
            title: 'Survey',
            key: 'survey',
            render: (_, row) => <SurveyNameCell surveyId={row.survey_id} surveyName={row.survey_name} />,
        },
        {
            title: 'Users shown',
            key: 'users_shown',
            align: 'right',
            render: (_, row) => humanFriendlyNumber(row.users_shown),
        },
        {
            title: 'Times shown',
            key: 'times_shown',
            align: 'right',
            render: (_, row) => humanFriendlyNumber(row.times_shown),
        },
        {
            title: 'Overloaded users',
            key: 'overloaded_users_shown',
            align: 'right',
            tooltip: 'Users who saw this survey and were shown too many surveys within the time window.',
            render: (_, row) =>
                `${humanFriendlyNumber(row.overloaded_users_shown)} (${humanFriendlyNumber(row.overloaded_users_rate)}%)`,
        },
        {
            title: 'Dismissal rate',
            key: 'dismissal_rate',
            align: 'right',
            tooltip: 'Share of users shown this survey who dismissed it. High values suggest annoyance.',
            render: (_, row) => `${humanFriendlyNumber(row.dismissal_rate)}%`,
        },
        {
            title: 'Response rate',
            key: 'response_rate',
            align: 'right',
            render: (_, row) => `${humanFriendlyNumber(row.response_rate)}%`,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <p className="text-secondary mb-0">
                Find users who are shown too many surveys in a short period. A user counts as overloaded when they see
                at least the configured number of different surveys within the time window. Tune the thresholds below
                and save them as the project default.
            </p>

            <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Time window</LemonLabel>
                    <LemonSelect
                        size="small"
                        value={config.window_seconds}
                        options={withCurrentValue(WINDOW_PRESETS, config.window_seconds, (value) =>
                            humanFriendlyDuration(value)
                        )}
                        onChange={(value) => value !== null && setConfigValue('window_seconds', value)}
                        data-attr="survey-load-detector-window"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel info="A user is overloaded when they are shown at least this many different surveys within the time window.">
                        Surveys per window
                    </LemonLabel>
                    <LemonInput
                        size="small"
                        type="number"
                        min={2}
                        max={50}
                        value={config.overload_threshold}
                        onChange={(value) =>
                            value !== undefined && value >= 2 && setConfigValue('overload_threshold', value)
                        }
                        data-attr="survey-load-detector-threshold"
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Period</LemonLabel>
                    <LemonSelect
                        size="small"
                        value={config.lookback_days}
                        options={withCurrentValue(
                            LOOKBACK_PRESETS,
                            config.lookback_days,
                            (value) => `Last ${value} days`
                        )}
                        onChange={(value) => value !== null && setConfigValue('lookback_days', value)}
                        data-attr="survey-load-detector-lookback"
                    />
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => loadAnalysis()}
                    loading={analysisLoading}
                    data-attr="survey-load-detector-refresh"
                >
                    Refresh
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => saveAsTeamDefault()}
                    loading={currentTeamLoading}
                    disabledReason={hasUnsavedChanges ? undefined : 'These are already the project defaults'}
                    tooltip="Requires project admin access"
                    data-attr="survey-load-detector-save-default"
                >
                    Save as project default
                </LemonButton>
            </div>

            {summary && summary.overloaded_users > 0 && (
                <LemonBanner type="warning">
                    {humanFriendlyNumber(summary.overloaded_users)} of {humanFriendlyNumber(summary.users_shown)} users
                    ({humanFriendlyNumber(summary.overloaded_users_rate)}%) were shown {config.overload_threshold} or
                    more surveys within {humanFriendlyDuration(config.window_seconds)}. Consider spacing surveys out
                    with a wait period, or narrowing their targeting.
                </LemonBanner>
            )}
            {summary && summary.overloaded_users === 0 && summary.users_shown > 0 && (
                <LemonBanner type="success">
                    No overloaded users found in this period. Your surveys are well spaced out.
                </LemonBanner>
            )}

            <StatRow
                isLoading={analysisLoading && !analysis}
                items={[
                    {
                        title: 'Users shown surveys',
                        value: humanFriendlyNumber(summary?.users_shown ?? 0),
                        description: 'Shown at least one survey',
                    },
                    {
                        title: 'Overloaded users',
                        value: humanFriendlyNumber(summary?.overloaded_users ?? 0),
                        description: `Saw ${config.overload_threshold}+ surveys within ${humanFriendlyDuration(
                            config.window_seconds
                        )}`,
                        valueClassName: summary && summary.overloaded_users > 0 ? 'text-warning' : 'text-success',
                    },
                    {
                        title: 'Overload rate',
                        value: `${humanFriendlyNumber(summary?.overloaded_users_rate ?? 0)}%`,
                        description: 'Of users shown surveys',
                    },
                ]}
            />

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Overlapping surveys</h3>
                <p className="text-secondary mb-0">
                    Pairs of surveys shown to the same user within the time window. These are the first candidates for
                    spacing out.
                </p>
                <LemonTable
                    dataSource={analysis?.overlaps ?? []}
                    columns={overlapColumns}
                    loading={analysisLoading}
                    rowKey={(overlap) => `${overlap.survey_id_1}-${overlap.survey_id_2}`}
                    emptyState="No surveys were shown together within the time window."
                    data-attr="survey-load-detector-overlaps"
                />
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Survey breakdown</h3>
                <p className="text-secondary mb-0">
                    How much each survey contributes to survey load, with dismissal rates as an annoyance signal.
                </p>
                <LemonTable
                    dataSource={analysis?.surveys ?? []}
                    columns={surveyColumns}
                    loading={analysisLoading}
                    rowKey={(row) => row.survey_id}
                    emptyState="No surveys were shown in this period."
                    data-attr="survey-load-detector-surveys"
                />
            </div>
        </div>
    )
}
