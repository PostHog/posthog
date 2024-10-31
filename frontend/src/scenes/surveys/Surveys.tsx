import { IconGear } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    Spinner,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { Customization } from 'scenes/surveys/SurveyCustomization'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivityScope, ProductKey, ProgressStatus, Survey } from '~/types'

import { defaultSurveyAppearance, NEW_SURVEY, SurveyQuestionLabel } from './constants'
import { openSurveysSettingsDialog } from './SurveySettings'
import { getSurveyStatus, surveysLogic, SurveysTabs } from './surveysLogic'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
}

export function Surveys(): JSX.Element {
    const {
        surveys,
        searchedSurveys,
        surveysLoading,
        surveysResponsesCount,
        surveysResponsesCountLoading,
        searchTerm,
        filters,
        showSurveysDisabledBanner,
        tab,
        globalSurveyAppearanceConfigAvailable,
    } = useValues(surveysLogic)

    const { deleteSurvey, updateSurvey, setSearchTerm, setSurveysFilters, setTab } = useActions(surveysLogic)

    const { user } = useValues(userLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const [editableSurveyConfig, setEditableSurveyConfig] = useState(
        currentTeam?.survey_config?.appearance || defaultSurveyAppearance
    )

    const [templatedSurvey, setTemplatedSurvey] = useState(NEW_SURVEY)

    if (templatedSurvey.appearance === defaultSurveyAppearance) {
        templatedSurvey.appearance = editableSurveyConfig
    }
    const shouldShowEmptyState = !surveysLoading && surveys.length === 0
    const showLinkedHogFunctions = useFeatureFlag('HOG_FUNCTIONS_LINKED')

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            to={urls.surveyTemplates()}
                            type="primary"
                            data-attr="new-survey"
                            sideAction={{
                                dropdown: {
                                    placement: 'bottom-start',
                                    actionable: true,
                                    overlay: (
                                        <LemonButton size="small" to={urls.survey('new')}>
                                            Create blank survey
                                        </LemonButton>
                                    ),
                                },
                                'data-attr': 'saved-insights-new-insight-dropdown',
                            }}
                        >
                            New survey
                        </LemonButton>
                    </>
                }
                caption={
                    <>
                        Check out our
                        <Link
                            data-attr="survey-help"
                            to="https://posthog.com/docs/surveys?utm_medium=in-product&utm_campaign=new-survey"
                            target="_blank"
                        >
                            {' '}
                            surveys docs
                        </Link>{' '}
                        to learn more.
                    </>
                }
                tabbedPage
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setTab(newTab as SurveysTabs)}
                tabs={[
                    { key: SurveysTabs.Active, label: 'Active' },
                    { key: SurveysTabs.Archived, label: 'Archived' },
                    showLinkedHogFunctions ? { key: SurveysTabs.Notifications, label: 'Notifications' } : null,
                    { key: SurveysTabs.History, label: 'History' },
                    globalSurveyAppearanceConfigAvailable ? { key: SurveysTabs.Settings, label: 'Settings' } : null,
                ]}
            />
            {tab === SurveysTabs.Settings && (
                <>
                    <div className="flex items-center mb-2 gap-2">
                        <LemonField.Pure className="mt-2" label="Appearance">
                            <span>These settings apply to new surveys in this organization.</span>
                        </LemonField.Pure>

                        <div className="flex-1" />
                        {globalSurveyAppearanceConfigAvailable && (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    updateCurrentTeam({
                                        survey_config: {
                                            ...currentTeam?.survey_config,
                                            appearance: {
                                                ...currentTeam?.survey_config?.appearance,
                                                ...editableSurveyConfig,
                                            },
                                        },
                                    })
                                }}
                            >
                                Save settings
                            </LemonButton>
                        )}
                    </div>
                    <LemonDivider />
                    <div className="flex align-top mb-2 gap-2">
                        <Customization
                            key="survey-settings-customization"
                            appearance={editableSurveyConfig}
                            hasBranchingLogic={false}
                            customizeRatingButtons={true}
                            customizePlaceholderText={true}
                            onAppearanceChange={(appearance) => {
                                setEditableSurveyConfig({
                                    ...editableSurveyConfig,
                                    ...appearance,
                                })
                                setTemplatedSurvey({
                                    ...templatedSurvey,
                                    ...{ appearance: appearance },
                                })
                            }}
                        />
                        <div className="flex-1" />
                        <div className="mt-10 mr-5">
                            {globalSurveyAppearanceConfigAvailable && (
                                <SurveyAppearancePreview survey={templatedSurvey} previewPageIndex={0} />
                            )}
                        </div>
                    </div>
                </>
            )}
            {tab === SurveysTabs.Notifications && (
                <>
                    <p>Get notified whenever a survey result is submitted</p>
                    <LinkedHogFunctions
                        type="destination"
                        subTemplateId="survey_response"
                        filters={{
                            events: [
                                {
                                    id: 'survey sent',
                                    type: 'events',
                                    order: 0,
                                },
                            ],
                        }}
                    />
                </>
            )}

            {tab === SurveysTabs.History && <ActivityLog scope={ActivityScope.SURVEY} />}

            {(tab === SurveysTabs.Active || tab === SurveysTabs.Archived) && (
                <>
                    <div className="space-y-2">
                        <VersionCheckerBanner />

                        {showSurveysDisabledBanner ? (
                            <LemonBanner
                                type="warning"
                                action={{
                                    type: 'secondary',
                                    icon: <IconGear />,
                                    onClick: () => openSurveysSettingsDialog(),
                                    children: 'Configure',
                                }}
                                className="mb-2"
                            >
                                Survey popovers are currently disabled for this project but there are active surveys
                                running. Re-enable them in the settings.
                            </LemonBanner>
                        ) : null}
                    </div>

                    {(shouldShowEmptyState || !user?.has_seen_product_intro_for?.[ProductKey.SURVEYS]) && (
                        <ProductIntroduction
                            productName="Surveys"
                            thingName="survey"
                            description="Use surveys to gather qualitative feedback from your users on new or existing features."
                            action={() => router.actions.push(urls.surveyTemplates())}
                            isEmpty={surveys.length === 0}
                            productKey={ProductKey.SURVEYS}
                        />
                    )}
                    {!shouldShowEmptyState && (
                        <>
                            <div>
                                <div className="flex justify-between mb-4 gap-2 flex-wrap">
                                    <LemonInput
                                        type="search"
                                        placeholder="Search for surveys"
                                        onChange={setSearchTerm}
                                        value={searchTerm || ''}
                                    />
                                    <div className="flex items-center gap-2">
                                        <span>
                                            <b>Status</b>
                                        </span>
                                        <LemonSelect
                                            dropdownMatchSelectWidth={false}
                                            onChange={(status) => {
                                                setSurveysFilters({ status })
                                            }}
                                            size="small"
                                            options={[
                                                { label: 'Any', value: 'any' },
                                                { label: 'Draft', value: 'draft' },
                                                { label: 'Running', value: 'running' },
                                                { label: 'Complete', value: 'complete' },
                                            ]}
                                            value={filters.status}
                                        />
                                        <span className="ml-1">
                                            <b>Created by</b>
                                        </span>
                                        <MemberSelect
                                            defaultLabel="Any user"
                                            value={filters.created_by ?? null}
                                            onChange={(user) => setSurveysFilters({ created_by: user?.id })}
                                        />
                                    </div>
                                </div>
                            </div>
                            <LemonTable
                                dataSource={searchedSurveys}
                                defaultSorting={{
                                    columnKey: 'created_at',
                                    order: -1,
                                }}
                                rowKey="name"
                                nouns={['survey', 'surveys']}
                                data-attr="surveys-table"
                                emptyState={
                                    tab === SurveysTabs.Active ? 'No surveys. Create a new survey?' : 'No surveys found'
                                }
                                loading={surveysLoading}
                                columns={[
                                    {
                                        dataIndex: 'name',
                                        title: 'Name',
                                        render: function RenderName(_, survey) {
                                            return (
                                                <LemonTableLink
                                                    to={urls.survey(survey.id)}
                                                    title={stringWithWBR(survey.name, 17)}
                                                />
                                            )
                                        },
                                    },
                                    {
                                        title: 'Responses',
                                        dataIndex: 'id',
                                        render: function RenderResponses(_, survey) {
                                            return (
                                                <>
                                                    {surveysResponsesCountLoading ? (
                                                        <Spinner />
                                                    ) : (
                                                        <div>{surveysResponsesCount[survey.id] ?? 0}</div>
                                                    )}
                                                </>
                                            )
                                        },
                                        sorter: (surveyA, surveyB) => {
                                            const countA = surveysResponsesCount[surveyA.id] ?? 0
                                            const countB = surveysResponsesCount[surveyB.id] ?? 0
                                            return countA - countB
                                        },
                                    },
                                    {
                                        dataIndex: 'type',
                                        title: 'Mode',
                                    },
                                    {
                                        title: 'Question type',
                                        render: function RenderResponses(_, survey) {
                                            return survey.questions?.length === 1
                                                ? SurveyQuestionLabel[survey.questions[0].type]
                                                : 'Multiple'
                                        },
                                    },
                                    createdByColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                                    createdAtColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                                    {
                                        title: 'Status',
                                        width: 100,
                                        render: function Render(_, survey: Survey) {
                                            return <StatusTag survey={survey} />
                                        },
                                    },
                                    {
                                        width: 0,
                                        render: function Render(_, survey: Survey) {
                                            return (
                                                <More
                                                    overlay={
                                                        <>
                                                            <LemonButton
                                                                fullWidth
                                                                onClick={() =>
                                                                    router.actions.push(urls.survey(survey.id))
                                                                }
                                                            >
                                                                View
                                                            </LemonButton>
                                                            {!survey.start_date && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() =>
                                                                        LemonDialog.open({
                                                                            title: 'Launch this survey?',
                                                                            content: (
                                                                                <div className="text-sm text-muted">
                                                                                    The survey will immediately start
                                                                                    displaying to users matching the
                                                                                    display conditions.
                                                                                </div>
                                                                            ),
                                                                            primaryButton: {
                                                                                children: 'Launch',
                                                                                type: 'primary',
                                                                                onClick: () => {
                                                                                    updateSurvey({
                                                                                        id: survey.id,
                                                                                        updatePayload: {
                                                                                            start_date:
                                                                                                dayjs().toISOString(),
                                                                                        },
                                                                                    })
                                                                                },
                                                                                size: 'small',
                                                                            },
                                                                            secondaryButton: {
                                                                                children: 'Cancel',
                                                                                type: 'tertiary',
                                                                                size: 'small',
                                                                            },
                                                                        })
                                                                    }
                                                                >
                                                                    Launch survey
                                                                </LemonButton>
                                                            )}
                                                            {survey.start_date && !survey.end_date && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        LemonDialog.open({
                                                                            title: 'Stop this survey?',
                                                                            content: (
                                                                                <div className="text-sm text-muted">
                                                                                    The survey will no longer be visible
                                                                                    to your users.
                                                                                </div>
                                                                            ),
                                                                            primaryButton: {
                                                                                children: 'Stop',
                                                                                type: 'primary',
                                                                                onClick: () => {
                                                                                    updateSurvey({
                                                                                        id: survey.id,
                                                                                        updatePayload: {
                                                                                            end_date:
                                                                                                dayjs().toISOString(),
                                                                                        },
                                                                                    })
                                                                                },
                                                                                size: 'small',
                                                                            },
                                                                            secondaryButton: {
                                                                                children: 'Cancel',
                                                                                type: 'tertiary',
                                                                                size: 'small',
                                                                            },
                                                                        })
                                                                    }}
                                                                >
                                                                    Stop survey
                                                                </LemonButton>
                                                            )}
                                                            {survey.end_date && !survey.archived && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        LemonDialog.open({
                                                                            title: 'Resume this survey?',
                                                                            content: (
                                                                                <div className="text-sm text-muted">
                                                                                    Once resumed, the survey will be
                                                                                    visible to your users again.
                                                                                </div>
                                                                            ),
                                                                            primaryButton: {
                                                                                children: 'Resume',
                                                                                type: 'primary',
                                                                                onClick: () => {
                                                                                    updateSurvey({
                                                                                        id: survey.id,
                                                                                        updatePayload: {
                                                                                            end_date: null,
                                                                                        },
                                                                                    })
                                                                                },
                                                                                size: 'small',
                                                                            },
                                                                            secondaryButton: {
                                                                                children: 'Cancel',
                                                                                type: 'tertiary',
                                                                                size: 'small',
                                                                            },
                                                                        })
                                                                    }}
                                                                >
                                                                    Resume survey
                                                                </LemonButton>
                                                            )}
                                                            <LemonDivider />
                                                            {survey.end_date && survey.archived && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() =>
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: { archived: false },
                                                                        })
                                                                    }
                                                                >
                                                                    Unarchive
                                                                </LemonButton>
                                                            )}
                                                            {survey.end_date && !survey.archived && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        LemonDialog.open({
                                                                            title: 'Archive this survey?',
                                                                            content: (
                                                                                <div className="text-sm text-muted">
                                                                                    This action will remove the survey
                                                                                    from your active surveys list. It
                                                                                    can be restored at any time.
                                                                                </div>
                                                                            ),
                                                                            primaryButton: {
                                                                                children: 'Archive',
                                                                                type: 'primary',
                                                                                onClick: () => {
                                                                                    updateSurvey({
                                                                                        id: survey.id,
                                                                                        updatePayload: {
                                                                                            archived: true,
                                                                                        },
                                                                                    })
                                                                                },
                                                                                size: 'small',
                                                                            },
                                                                            secondaryButton: {
                                                                                children: 'Cancel',
                                                                                type: 'tertiary',
                                                                                size: 'small',
                                                                            },
                                                                        })
                                                                    }}
                                                                >
                                                                    Archive
                                                                </LemonButton>
                                                            )}
                                                            <LemonButton
                                                                status="danger"
                                                                onClick={() => {
                                                                    LemonDialog.open({
                                                                        title: 'Delete this survey?',
                                                                        content: (
                                                                            <div className="text-sm text-muted">
                                                                                This action cannot be undone. All survey
                                                                                data will be permanently removed.
                                                                            </div>
                                                                        ),
                                                                        primaryButton: {
                                                                            children: 'Delete',
                                                                            type: 'primary',
                                                                            onClick: () => deleteSurvey(survey.id),
                                                                            size: 'small',
                                                                        },
                                                                        secondaryButton: {
                                                                            children: 'Cancel',
                                                                            type: 'tertiary',
                                                                            size: 'small',
                                                                        },
                                                                    })
                                                                }}
                                                                fullWidth
                                                            >
                                                                Delete
                                                            </LemonButton>
                                                        </>
                                                    }
                                                />
                                            )
                                        },
                                    },
                                ]}
                            />
                        </>
                    )}
                </>
            )}
        </div>
    )
}

export function StatusTag({ survey }: { survey: Survey }): JSX.Element {
    const statusColors = {
        running: 'success',
        draft: 'default',
        complete: 'completion',
    } as Record<ProgressStatus, LemonTagType>
    const status = getSurveyStatus(survey)
    return (
        <LemonTag type={statusColors[status]} className="font-semibold" data-attr="status">
            {status.toUpperCase()}
        </LemonTag>
    )
}
