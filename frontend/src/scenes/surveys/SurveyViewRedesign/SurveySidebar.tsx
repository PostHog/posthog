import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, Link } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
import { NewSurvey, SURVEY_TYPE_LABEL_MAP } from 'scenes/surveys/constants'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getNextPreviewPageIndex } from 'scenes/surveys/surveyPreviewNavigation'
import {
    clampPreviewPageIndex,
    getIntroScreenPageOptions,
    getRecurringSurveyScheduleInfo,
    getSurveyCollectionLimitSummary,
    getSurveyDisplayConditionsSummary,
} from 'scenes/surveys/utils'

import {
    AccessControlLevel,
    AccessControlResourceType,
    ExporterFormat,
    Survey,
    SurveySchedule as SurveyScheduleEnum,
    SurveyType,
} from '~/types'

import { SurveyConditionsList } from '../components/SurveyConditions'
import { CopySurveyLink } from '../CopySurveyLink'

// ============================================================================
// Panel Section - Wrapper for consistent panel styling
// ============================================================================

interface PanelSectionProps {
    title: string
    description?: string
    children: ReactNode
}

function PanelSection({ title, description, children }: PanelSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div>
                <div className="text-xs font-semibold uppercase tracking-wide">{title}</div>
                {description && <p className="text-xs text-muted m-0 mt-1">{description}</p>}
            </div>
            {children}
        </div>
    )
}

function formatSurveySchedule(survey: Survey): string {
    if (survey.schedule === SurveyScheduleEnum.Recurring && survey.iteration_count && survey.iteration_frequency_days) {
        return `Show up to ${survey.iteration_count} ${pluralize(
            survey.iteration_count,
            'time',
            'times',
            false
        )} total, once every ${pluralize(survey.iteration_frequency_days, 'day')}`
    }

    if (survey.schedule === SurveyScheduleEnum.Always) {
        return 'Always'
    }

    return 'Once'
}

// ============================================================================
// Panel Components
// ============================================================================

export interface SurveyAtAGlanceRow {
    key: string
    label: string
    value: ReactNode
}

export function getSurveyAtAGlanceRows(survey: Survey, hasTargetingSet: boolean): SurveyAtAGlanceRow[] {
    const collectionLimitSummary = getSurveyCollectionLimitSummary(survey)
    const scheduleInfo = getRecurringSurveyScheduleInfo(survey)
    const rows: (SurveyAtAGlanceRow | null)[] = [
        {
            key: 'status',
            label: 'Status',
            value: !survey.start_date ? 'Draft' : survey.end_date ? 'Complete' : 'Running',
        },
        { key: 'type', label: 'Type', value: SURVEY_TYPE_LABEL_MAP[survey.type] },
        { key: 'schedule', label: 'Schedule', value: formatSurveySchedule(survey) },
        scheduleInfo
            ? {
                  key: 'auto-closes',
                  label: 'Auto-closes',
                  value: scheduleInfo.autoCloseDate
                      ? scheduleInfo.autoCloseDate.isBefore(dayjs())
                          ? 'Soon'
                          : scheduleInfo.autoCloseDate.format('MMMM D, YYYY')
                      : `After ${pluralize(scheduleInfo.totalDurationDays, 'day')}`,
              }
            : null,
        { key: 'audience', label: 'Audience', value: hasTargetingSet ? 'Targeted' : 'All users' },
        survey.start_date ? { key: 'started', label: 'Started', value: <TZLabel time={survey.start_date} /> } : null,
        survey.end_date ? { key: 'ended', label: 'Ended', value: <TZLabel time={survey.end_date} /> } : null,
        collectionLimitSummary
            ? { key: 'collection-limit', label: collectionLimitSummary.label, value: collectionLimitSummary.value }
            : null,
    ]
    return rows.filter((row): row is SurveyAtAGlanceRow => row !== null)
}

export function getSurveyPreviewPageOptions(
    survey: Pick<Survey | NewSurvey, 'questions' | 'appearance'>
): { label: string; value: number }[] {
    return [
        ...getIntroScreenPageOptions(survey),
        ...survey.questions.map((question, index) => ({
            label: `${index + 1}. ${question.question ?? ''}`,
            value: index,
        })),
        ...(survey.appearance?.displayThankYouMessage
            ? [{ label: 'Thank you message', value: survey.questions.length }]
            : []),
    ]
}

export const SURVEY_NO_RESPONSES_TO_EXPORT = 'No responses to export yet.'

export const SURVEY_API_DOCS_URL = 'https://posthog.com/docs/surveys/implementing-custom-surveys'

interface SurveyResponsesExport {
    disabledReason: string | null
    exportResponses: (format: ExporterFormat.CSV | ExporterFormat.XLSX) => void
}

export function useSurveyResponsesExport(): SurveyResponsesExport {
    const { survey, responsesExportQuery } = useValues(surveyLogic)
    const { startExport } = useActions(exportsLogic)

    const exportAccessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Export,
        AccessControlLevel.Editor
    )

    return {
        disabledReason: !responsesExportQuery
            ? SURVEY_NO_RESPONSES_TO_EXPORT
            : (exportAccessControlDisabledReason ?? null),
        exportResponses: (format) => {
            if (!responsesExportQuery) {
                return
            }
            startExport({
                export_format: format,
                export_context: {
                    source: responsesExportQuery,
                    columns: responsesExportQuery.columns,
                    filename: `survey-${survey.name}-responses`,
                },
            })
        },
    }
}

export function SurveyDetailsPanel(): JSX.Element {
    const { survey, selectedPageIndex, hasTargetingSet } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const isNonApiSurvey = survey.type !== SurveyType.API
    const conditionsSummary = hasTargetingSet ? getSurveyDisplayConditionsSummary(survey as Survey) : []
    const effectivePageIndex = clampPreviewPageIndex(selectedPageIndex, survey)

    return (
        <div className="flex flex-col gap-6">
            {/* Preview */}
            {isNonApiSurvey && (
                <PanelSection title="Preview">
                    <div className="flex flex-col gap-3">
                        <div className="flex justify-center">
                            <SurveyAppearancePreview
                                survey={survey as Survey}
                                previewPageIndex={effectivePageIndex}
                                onPreviewSubmit={(response) => {
                                    const nextPageIndex = getNextPreviewPageIndex(survey, effectivePageIndex, response)
                                    if (nextPageIndex !== null) {
                                        setSelectedPageIndex(nextPageIndex)
                                    }
                                }}
                            />
                        </div>
                        <LemonSelect
                            size="xsmall"
                            fullWidth
                            value={effectivePageIndex}
                            onChange={(pageIndex) => setSelectedPageIndex(pageIndex)}
                            options={getSurveyPreviewPageOptions(survey)}
                        />
                    </div>
                </PanelSection>
            )}

            {/* Survey info */}
            <PanelSection title="At a glance">
                <div className="flex flex-col gap-1.5 text-sm">
                    {getSurveyAtAGlanceRows(survey as Survey, hasTargetingSet).map((row) => (
                        <div key={row.key} className="flex justify-between">
                            <span className="text-muted">{row.label}</span>
                            <span>{row.value}</span>
                        </div>
                    ))}
                    {survey.type === SurveyType.ExternalSurvey && (
                        <div className="flex flex-col gap-2 pt-1">
                            <span className="text-muted text-xs">Share link</span>
                            <CopySurveyLink
                                surveyId={survey.id}
                                enableIframeEmbedding={survey.enable_iframe_embedding ?? false}
                            />
                        </div>
                    )}
                    {survey.type === SurveyType.API && (
                        <div className="flex justify-between">
                            <span className="text-muted">API docs</span>
                            <Link to={SURVEY_API_DOCS_URL} target="_blank">
                                View docs
                            </Link>
                        </div>
                    )}
                </div>
            </PanelSection>

            {conditionsSummary.length > 0 && (
                <PanelSection title="Display conditions">
                    <SurveyConditionsList conditions={conditionsSummary} />
                </PanelSection>
            )}
        </div>
    )
}

export function SurveyExportPanel(): JSX.Element {
    const { responsesExportQuery } = useValues(surveyLogic)
    const { disabledReason, exportResponses } = useSurveyResponsesExport()

    return (
        <PanelSection title="Export" description="Download survey responses">
            {responsesExportQuery ? (
                <LemonMenu
                    items={[
                        {
                            label: 'Export as CSV',
                            onClick: () => exportResponses(ExporterFormat.CSV),
                            disabledReason: disabledReason ?? undefined,
                        },
                        {
                            label: 'Export as Excel',
                            onClick: () => exportResponses(ExporterFormat.XLSX),
                            disabledReason: disabledReason ?? undefined,
                        },
                    ]}
                >
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        icon={<IconDownload />}
                        data-attr="export-survey-responses"
                    >
                        Export responses
                    </LemonButton>
                </LemonMenu>
            ) : (
                <p className="text-xs text-muted m-0">{SURVEY_NO_RESPONSES_TO_EXPORT}</p>
            )}
        </PanelSection>
    )
}
