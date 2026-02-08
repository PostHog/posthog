import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { getNextSurveyStep } from 'posthog-js/dist/surveys-preview'
import { ReactNode, useState } from 'react'

import { IconBell, IconDownload, IconInfo, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { SurveyHeadline } from 'scenes/surveys/SurveyHeadline'
import { SURVEY_TYPE_LABEL_MAP } from 'scenes/surveys/constants'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { urls } from 'scenes/urls'

import {
    ExporterFormat,
    PropertyFilterType,
    PropertyOperator,
    Survey,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionBranchingType,
    SurveyType,
} from '~/types'

import { HogFunctionIcon } from '../../hog-functions/configuration/HogFunctionIcon'

// ============================================================================
// Sidebar Container
// ============================================================================

interface SidebarTab {
    key: SurveySidebarTab
    icon: JSX.Element
    label: string
    content: ReactNode
}

function SidebarContainer({ tabs, defaultTab }: { tabs: SidebarTab[]; defaultTab?: SurveySidebarTab }): JSX.Element {
    const [activeTab, setActiveTab] = useState<SurveySidebarTab | null>(defaultTab ?? tabs[0]?.key ?? null)
    const activeTabContent = activeTab ? tabs.find((tab) => tab.key === activeTab)?.content : null
    const isExpanded = activeTab !== null

    return (
        <div className={`flex shrink-0 border-l sticky top-8 h-screen ${isExpanded ? 'w-[420px]' : ''}`}>
            {/* Tab content with padding - only show if a tab is selected */}
            {activeTab && <div className="flex-1 overflow-y-auto p-3">{activeTabContent}</div>}

            {/* Vertical tab bar - right side */}
            <div className="flex flex-col gap-0.5 px-1 pb-1 pt-3 border-l first:border-l-0">
                {tabs.map((tab) => (
                    <Tooltip key={tab.key} title={tab.label} placement="left">
                        <LemonButton
                            size="small"
                            icon={tab.icon}
                            active={activeTab === tab.key}
                            onClick={() => setActiveTab(activeTab === tab.key ? null : tab.key)}
                        />
                    </Tooltip>
                ))}
            </div>
        </div>
    )
}

// ============================================================================
// Sidebar Panel - Wrapper for consistent panel styling
// ============================================================================

interface SidebarPanelProps {
    title: string
    description?: string
    children: ReactNode
}

function SidebarPanel({ title, description, children }: SidebarPanelProps): JSX.Element {
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
// Survey Sidebar - Main export
// ============================================================================

type SurveySidebarTab = 'details' | 'notifications' | 'insights' | 'export'

export function SurveySidebar(): JSX.Element {
    const { survey, isSurveyHeadlineEnabled } = useValues(surveyLogic)
    const isDraft = !survey.start_date

    const tabs: SidebarTab[] = [
        {
            key: 'details',
            icon: <IconInfo />,
            label: 'Details',
            content: <DetailsPanel />,
        },
        {
            key: 'notifications',
            icon: <IconBell />,
            label: 'Notifications',
            content: <NotificationsPanel surveyId={survey.id} />,
        },
        ...(!isDraft && isSurveyHeadlineEnabled
            ? [
                  {
                      key: 'insights' as const,
                      icon: <IconSparkles />,
                      label: 'AI insights',
                      content: <InsightsPanel />,
                  },
              ]
            : []),
        ...(!isDraft
            ? [
                  {
                      key: 'export' as const,
                      icon: <IconDownload />,
                      label: 'Export',
                      content: <ExportPanel />,
                  },
              ]
            : []),
    ]

    return <SidebarContainer tabs={tabs} defaultTab="details" />
}

/** Stacked sidebar content for mobile Details tab (no notifications - they have their own tab) */
export function SurveySidebarContent(): JSX.Element {
    const { survey, isSurveyHeadlineEnabled } = useValues(surveyLogic)
    const isDraft = !survey.start_date

    return (
        <div className="flex flex-col gap-6 px-4 pb-4">
            <DetailsPanel />
            {!isDraft && isSurveyHeadlineEnabled && <InsightsPanel />}
        </div>
    )
}

/** Notifications content for mobile tab */
export function SurveyNotificationsContent(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    return (
        <div className="flex flex-col gap-3 px-4 pb-4">
            <p className="text-xs text-muted m-0">Get notified when responses come in</p>
            <NotificationsPanel surveyId={survey.id} showTitle={false} />
        </div>
    )
}

/** Export content for mobile tab */
export function SurveyExportContent(): JSX.Element {
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
        <div className="flex flex-col gap-3 px-4 pb-4">
            <p className="text-xs text-muted m-0">Download survey responses</p>
            {dataTableQuery ? (
                <div className="flex flex-col gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        icon={<IconDownload />}
                        onClick={() => handleExport(ExporterFormat.CSV)}
                        data-attr="export-survey-responses-csv"
                    >
                        Export as CSV
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        fullWidth
                        icon={<IconDownload />}
                        onClick={() => handleExport(ExporterFormat.XLSX)}
                        data-attr="export-survey-responses-xlsx"
                    >
                        Export as Excel
                    </LemonButton>
                </div>
            ) : (
                <p className="text-xs text-muted m-0">No responses to export yet.</p>
            )}
        </div>
    )
}

// ============================================================================
// Panel Components
// ============================================================================

const NOTIFICATION_OPTIONS = [
    { id: 'template-slack', name: 'Slack', iconUrl: '/static/services/slack.png' },
    { id: 'template-discord', name: 'Discord', iconUrl: '/static/services/discord.png' },
    { id: 'template-microsoft-teams', name: 'Teams', iconUrl: '/static/services/microsoft-teams.png' },
    { id: 'template-webhook', name: 'Webhook', iconUrl: '/static/services/webhook.svg' },
]

function getNotificationUrl(templateId: string, surveyId: string): string {
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
    return combineUrl(urls.hogFunctionNew(templateId), {}, { configuration: { filters } }).url
}

function NotificationsPanel({ surveyId, showTitle = true }: { surveyId: string; showTitle?: boolean }): JSX.Element {
    const content = (
        <div className="flex flex-col gap-1">
            {NOTIFICATION_OPTIONS.map((option) => (
                <LemonButton
                    key={option.id}
                    type="tertiary"
                    size="small"
                    fullWidth
                    to={getNotificationUrl(option.id, surveyId)}
                    targetBlank
                    className="justify-start"
                >
                    <HogFunctionIcon src={option.iconUrl} size="small" />
                    <span className="ml-2">{option.name}</span>
                </LemonButton>
            ))}
        </div>
    )

    if (!showTitle) {
        return content
    }

    return (
        <SidebarPanel title="Notifications" description="Get notified when responses come in">
            {content}
        </SidebarPanel>
    )
}

function DetailsPanel(): JSX.Element {
    const { survey, selectedPageIndex } = useValues(surveyLogic)
    const { setSelectedPageIndex } = useActions(surveyLogic)
    const isNonApiSurvey = survey.type !== SurveyType.API

    return (
        <div className="flex flex-col gap-6">
            {/* Preview */}
            {isNonApiSurvey && (
                <SidebarPanel title="Preview">
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
                </SidebarPanel>
            )}

            {/* Survey info */}
            <SidebarPanel title="Details">
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
            </SidebarPanel>
        </div>
    )
}

function ExportPanel(): JSX.Element {
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
        <SidebarPanel title="Export" description="Download survey responses">
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
        </SidebarPanel>
    )
}

function InsightsPanel(): JSX.Element {
    return (
        <SidebarPanel title="AI insights">
            <SurveyHeadline />
        </SidebarPanel>
    )
}
