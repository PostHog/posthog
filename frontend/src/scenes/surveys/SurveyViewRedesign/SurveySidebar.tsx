import { useActions, useValues } from 'kea'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { ReactNode } from 'react'

import { IconDownload, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { SURVEY_TYPE_LABEL_MAP } from 'scenes/surveys/constants'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import {
    getSurveyCollectionLimitSummary,
    getSurveyDisplayConditionsSummary,
    newSurveyNotificationUrl,
} from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import {
    ExporterFormat,
    HogFunctionType,
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

function getNotificationDescription(fn: HogFunctionType): string | null {
    const inputs = fn.inputs
    if (!inputs) {
        return null
    }
    if (inputs.url?.value) {
        try {
            return new URL(String(inputs.url.value)).hostname
        } catch {
            return String(inputs.url.value)
        }
    }
    if (inputs.channel?.value) {
        return String(inputs.channel.value)
    }
    if (inputs.email?.value) {
        return String(inputs.email.value)
    }
    return null
}

export function SurveyNotificationsPanel(): JSX.Element {
    const { survey, surveyNotifications, surveyNotificationsLoading } = useValues(surveyLogic)
    const { toggleSurveyNotificationEnabled } = useActions(surveyLogic)

    if (surveyNotificationsLoading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-12" />
                <LemonSkeleton className="h-12" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {surveyNotifications.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                    {surveyNotifications.map((fn) => {
                        const description = getNotificationDescription(fn)
                        return (
                            <div key={fn.id} className="flex items-center gap-2 rounded border p-2">
                                <HogFunctionIcon src={fn.icon_url} size="small" />
                                <div className="flex-1 min-w-0">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={urls.hogFunction(fn.id)}
                                        className="font-medium p-0 h-auto min-h-0"
                                        noPadding
                                    >
                                        <span className="truncate">{fn.name}</span>
                                    </LemonButton>
                                    {description && <div className="text-xs text-muted truncate">{description}</div>}
                                </div>
                                <LemonSwitch
                                    checked={fn.enabled}
                                    onChange={() => toggleSurveyNotificationEnabled(fn.id, !fn.enabled)}
                                    size="small"
                                />
                            </div>
                        )
                    })}
                </div>
            ) : (
                <p className="text-xs text-muted m-0">No notifications configured yet.</p>
            )}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                to={newSurveyNotificationUrl(survey.id)}
                fullWidth
            >
                New notification
            </LemonButton>
        </div>
    )
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
