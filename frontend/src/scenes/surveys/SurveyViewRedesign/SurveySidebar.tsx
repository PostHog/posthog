import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { ReactNode, useEffect, useState } from 'react'

import { IconDownload, IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import api from 'lib/api'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { SURVEY_TYPE_LABEL_MAP } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { urls } from 'scenes/urls'

import {
    ExporterFormat,
    HogFunctionType,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionBranchingType,
    SurveyType,
} from '~/types'

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

// ============================================================================
// Panel Components
// ============================================================================

export function SurveyDetailsPanel(): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const isNonApiSurvey = survey.type !== SurveyType.API

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
            <PanelSection title="Details">
                <div className="flex flex-col gap-1.5 text-sm">
                    <div className="flex justify-between">
                        <span className="text-muted">Type</span>
                        <span>{SURVEY_TYPE_LABEL_MAP[survey.type]}</span>
                    </div>
                    <div className="flex justify-between">
                        <span className="text-muted">Questions</span>
                        <span>{survey.questions.length}</span>
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
                    {survey.responses_limit && (
                        <div className="flex justify-between">
                            <span className="text-muted">Response limit</span>
                            <span>{survey.responses_limit}</span>
                        </div>
                    )}
                </div>
            </PanelSection>
        </div>
    )
}

function newNotificationUrl(surveyId: string): string {
    const filters = {
        events: [
            {
                id: SurveyEventName.SENT,
                type: 'events',
                properties: [
                    {
                        key: SurveyEventProperties.SURVEY_ID,
                        type: PropertyFilterType.Event,
                        value: surveyId,
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ],
    }
    return combineUrl(urls.hogFunctionNew('template-webhook'), {}, { configuration: { filters } }).url
}

function getNotificationDescription(fn: HogFunctionType): string | null {
    const inputs = fn.inputs
    if (!inputs) {
        return null
    }
    // Try common destination fields for a useful summary
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
    const { survey } = useValues(surveyLogic)
    const [hogFunctions, setHogFunctions] = useState<HogFunctionType[]>([])
    const [loading, setLoading] = useState(true)

    const loadFunctions = (): void => {
        setLoading(true)
        void api.hogFunctions
            .list({
                filter_groups: [
                    {
                        events: [
                            {
                                id: SurveyEventName.SENT,
                                type: 'events',
                                properties: [
                                    {
                                        key: SurveyEventProperties.SURVEY_ID,
                                        type: PropertyFilterType.Event,
                                        value: survey.id,
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                ],
                types: ['destination'],
                full: true,
            })
            .then((res) => setHogFunctions(res.results))
            .finally(() => setLoading(false))
    }

    useEffect(() => {
        loadFunctions()
    }, [survey.id])

    const toggleEnabled = (fn: HogFunctionType): void => {
        const newEnabled = !fn.enabled
        setHogFunctions((prev) => prev.map((f) => (f.id === fn.id ? { ...f, enabled: newEnabled } : f)))
        void api.hogFunctions.update(fn.id, { enabled: newEnabled })
    }

    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-12" />
                <LemonSkeleton className="h-12" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {hogFunctions.length > 0 ? (
                <div className="flex flex-col gap-1.5">
                    {hogFunctions.map((fn) => {
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
                                <LemonSwitch checked={fn.enabled} onChange={() => toggleEnabled(fn)} size="small" />
                            </div>
                        )
                    })}
                </div>
            ) : (
                <p className="text-xs text-muted m-0">No notifications configured yet.</p>
            )}
            <LemonButton type="secondary" size="small" icon={<IconPlus />} to={newNotificationUrl(survey.id)} fullWidth>
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
