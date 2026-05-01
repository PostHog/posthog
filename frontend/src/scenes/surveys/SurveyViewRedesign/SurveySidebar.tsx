import { useActions, useValues } from 'kea'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { ReactNode } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, Link } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils'
import { SurveyNotifications } from 'scenes/surveys/components/SurveyNotifications'
import { SURVEY_TYPE_LABEL_MAP } from 'scenes/surveys/constants'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyCollectionLimitSummary, getSurveyDisplayConditionsSummary } from 'scenes/surveys/utils'

import {
    ExporterFormat,
    Survey,
    SurveyQuestionBranchingType,
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

export function SurveyDetailsPanel(): JSX.Element {
    const { survey, selectedPageIndex, hasTargetingSet } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const isNonApiSurvey = survey.type !== SurveyType.API
    const statusLabel = !survey.start_date ? 'Draft' : survey.end_date ? 'Complete' : 'Running'
    const conditionsSummary = hasTargetingSet ? getSurveyDisplayConditionsSummary(survey as Survey) : []
    const collectionLimitSummary = getSurveyCollectionLimitSummary(survey)

    return (
        <div className="flex flex-col gap-6">
            {/* Preview */}
            {isNonApiSurvey && (
                <PanelSection title="Preview">
                    <div className="flex flex-col gap-3">
                        <div className="flex justify-center">
                            <SurveyAppearancePreview
                                survey={survey as Survey}
                                previewPageIndex={selectedPageIndex || 0}
                                onPreviewSubmit={(response) => {
                                    const nextStep = getNextSurveyStep(survey, selectedPageIndex, response)
                                    if (
                                        nextStep === SurveyQuestionBranchingType.End &&
                                        !survey.appearance?.displayThankYouMessage
                                    ) {
                                        return
                                    }
                                    setSelectedPageIndex(
                                        nextStep === SurveyQuestionBranchingType.End
                                            ? survey.questions.length
                                            : nextStep
                                    )
                                }}
                            />
                        </div>
                        <LemonSelect
                            size="xsmall"
                            fullWidth
                            value={selectedPageIndex || 0}
                            onChange={(pageIndex) => setSelectedPageIndex(pageIndex)}
                            options={[
                                ...survey.questions.map((question, index) => ({
                                    label: `${index + 1}. ${question.question ?? ''}`,
                                    value: index,
                                })),
                                ...(survey.appearance?.displayThankYouMessage
                                    ? [{ label: 'Thank you message', value: survey.questions.length }]
                                    : []),
                            ]}
                        />
                    </div>
                </PanelSection>
            )}

            {/* Survey info */}
            <PanelSection title="At a glance">
                <div className="flex flex-col gap-1.5 text-sm">
                    <div className="flex justify-between">
                        <span className="text-muted">Status</span>
                        <span>{statusLabel}</span>
                    </div>
                    <div className="flex justify-between">
                        <span className="text-muted">Type</span>
                        <span>{SURVEY_TYPE_LABEL_MAP[survey.type]}</span>
                    </div>
                    <div className="flex justify-between">
                        <span className="text-muted">Schedule</span>
                        <span>{formatSurveySchedule(survey as Survey)}</span>
                    </div>
                    <div className="flex justify-between">
                        <span className="text-muted">Audience</span>
                        <span>{hasTargetingSet ? 'Targeted' : 'All users'}</span>
                    </div>
                    {survey.start_date && (
                        <div className="flex justify-between">
                            <span className="text-muted">Started</span>
                            <TZLabel time={survey.start_date} />
                        </div>
                    )}
                    {survey.end_date && (
                        <div className="flex justify-between">
                            <span className="text-muted">Ended</span>
                            <TZLabel time={survey.end_date} />
                        </div>
                    )}
                    {collectionLimitSummary && (
                        <div className="flex justify-between">
                            <span className="text-muted">{collectionLimitSummary.label}</span>
                            <span>{collectionLimitSummary.value}</span>
                        </div>
                    )}
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
                            <Link to="https://posthog.com/docs/surveys/implementing-custom-surveys" target="_blank">
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

export function SurveyNotificationsPanel(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    return <SurveyNotifications surveyId={survey.id} buttonFullWidth />
}

export function SurveyExportPanel(): JSX.Element {
    const { survey, dataTableQuery } = useValues(surveyLogic)
    const { startExport } = useActions(exportsLogic)

    const handleExport = (format: ExporterFormat): void => {
        if (!dataTableQuery) {
            return
        }
        startExport({
            export_format: format,
            export_context: {
                source: dataTableQuery,
                filename: `survey-${survey.name}-responses`,
            },
        })
    }

    return (
        <PanelSection title="Export" description="Download survey responses">
            {dataTableQuery ? (
                <LemonMenu
                    items={[
                        {
                            label: 'Export as CSV',
                            onClick: () => handleExport(ExporterFormat.CSV),
                        },
                        {
                            label: 'Export as Excel',
                            onClick: () => handleExport(ExporterFormat.XLSX),
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
                <p className="text-xs text-muted m-0">No responses to export yet.</p>
            )}
        </PanelSection>
    )
}
