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
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import stringWithWBR from 'lib/utils/stringWithWBR'
import posthog from 'posthog-js'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import MaxTool from 'scenes/max/MaxTool'
import { SceneExport } from 'scenes/sceneTypes'
import { isSurveyRunning } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivityScope, ProductKey, ProgressStatus, Survey } from '~/types'

import { ProductIntentContext } from 'lib/utils/product-intents'
import { SURVEY_TYPE_LABEL_MAP, SurveyQuestionLabel } from './constants'
import { SurveysDisabledBanner, SurveySettings } from './SurveySettings'
import { getSurveyStatus, surveysLogic, SurveysTabs } from './surveysLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
    settingSectionId: 'environment-surveys',
}

function NewSurveyButton(): JSX.Element {
    const { loadSurveys } = useActions(surveysLogic)
    const { user } = useValues(userLogic)

    const button = (
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
    )

    // If the user is not loaded, just show the button without Max tool
    if (!user?.uuid) {
        return button
    }

    return (
        <MaxTool
            name="create_survey"
            description="Max can create surveys to collect qualitative feedback from your users on new or existing features."
            displayName="Create survey"
            initialMaxPrompt="Create a survey to collect "
            suggestions={[
                'Create an NPS survey for customers who completed checkout',
                'Create a feedback survey asking about our new dashboard',
                'Create a product-market fit survey for trial users',
                'Create a quick satisfaction survey for support interactions',
            ]}
            context={{
                user_id: user.uuid,
            }}
            callback={(toolOutput: { survey_id?: string; survey_name?: string; error?: string }) => {
                if (toolOutput?.error || !toolOutput?.survey_id) {
                    posthog.captureException('survey-creation-failed', {
                        error: toolOutput.error,
                    })
                    return
                }

                // Refresh surveys list to show new survey, then redirect to it
                loadSurveys()
                router.actions.push(urls.survey(toolOutput.survey_id))
            }}
        >
            {button}
        </MaxTool>
    )
}

function Surveys(): JSX.Element {
    const {
        data: { surveys },
        searchedSurveys,
        dataLoading,
        surveysResponsesCount,
        surveysResponsesCountLoading,
        searchTerm,
        filters,
        tab,
        hasNextPage,
        hasNextSearchPage,
    } = useValues(surveysLogic)

    const { deleteSurvey, updateSurvey, setSearchTerm, setSurveysFilters, setTab, loadNextPage, loadNextSearchPage } =
        useActions(surveysLogic)

    const { user } = useValues(userLogic)
    const shouldShowEmptyState = !dataLoading && surveys.length === 0
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            size="small"
                            type={!newSceneLayout ? 'secondary' : undefined}
                            id="surveys-page-feedback-button"
                            tooltip={newSceneLayout ? 'Have any questions or feedback?' : undefined}
                        >
                            {!newSceneLayout ? <>Have any questions or feedback?</> : <>Feedback</>}
                        </LemonButton>
                        <NewSurveyButton />
                    </>
                }
                className="flex gap-2 justify-between items-center min-w-full"
                caption={
                    <>
                        <div>
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
                        </div>
                    </>
                }
                tabbedPage
            />
            <SurveysDisabledBanner />
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setTab(newTab as SurveysTabs)}
                tabs={[
                    { key: SurveysTabs.Active, label: 'Active' },
                    { key: SurveysTabs.Archived, label: 'Archived' },
                    { key: SurveysTabs.Notifications, label: 'Notifications' },
                    { key: SurveysTabs.History, label: 'History' },
                    { key: SurveysTabs.Settings, label: 'Settings' },
                ]}
            />
            {tab === SurveysTabs.Settings && <SurveySettings />}
            {tab === SurveysTabs.Notifications && (
                <>
                    <p>Get notified whenever a survey result is submitted</p>
                    <LinkedHogFunctions type="destination" subTemplateIds={['survey-response']} />
                </>
            )}

            {tab === SurveysTabs.History && <ActivityLog scope={ActivityScope.SURVEY} />}

            {(tab === SurveysTabs.Active || tab === SurveysTabs.Archived) && (
                <>
                    <div className="deprecated-space-y-2">
                        <VersionCheckerBanner />
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
                                <div className="flex flex-wrap gap-2 justify-between mb-4">
                                    <LemonInput
                                        type="search"
                                        placeholder="Search for surveys"
                                        onChange={setSearchTerm}
                                        value={searchTerm || ''}
                                    />
                                    <div className="flex gap-2 items-center">
                                        {tab === SurveysTabs.Active && (
                                            <>
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
                                            </>
                                        )}
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
                                loading={dataLoading}
                                footer={
                                    (searchTerm ? hasNextSearchPage : hasNextPage) && (
                                        <div className="flex justify-center p-1">
                                            <LemonButton
                                                onClick={searchTerm ? loadNextSearchPage : loadNextPage}
                                                className="min-w-full text-center"
                                                disabledReason={dataLoading ? 'Loading surveys' : ''}
                                            >
                                                <span className="flex-1 text-center">
                                                    {dataLoading ? 'Loading...' : 'Load more'}
                                                </span>
                                            </LemonButton>
                                        </div>
                                    )
                                }
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
                                        render: function RenderType(_, survey) {
                                            return SURVEY_TYPE_LABEL_MAP[survey.type]
                                        },
                                    },
                                    {
                                        title: 'Question type',
                                        render: function RenderResponses(_, survey) {
                                            return survey.questions?.length === 1
                                                ? SurveyQuestionLabel[survey.questions[0].type]
                                                : 'Multiple'
                                        },
                                    },
                                    ...(tab === SurveysTabs.Active
                                        ? [
                                              createdAtColumn<Survey>() as LemonTableColumn<
                                                  Survey,
                                                  keyof Survey | undefined
                                              >,
                                              {
                                                  title: 'Status',
                                                  width: 100,
                                                  render: function Render(_: any, survey: Survey) {
                                                      return <StatusTag survey={survey} />
                                                  },
                                              },
                                          ]
                                        : []),
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
                                                                                <div className="text-sm text-secondary">
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
                                                                                        intentContext:
                                                                                            ProductIntentContext.SURVEY_LAUNCHED,
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
                                                            {isSurveyRunning(survey) && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        LemonDialog.open({
                                                                            title: 'Stop this survey?',
                                                                            content: (
                                                                                <div className="text-sm text-secondary">
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
                                                                                        intentContext:
                                                                                            ProductIntentContext.SURVEY_COMPLETED,
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
                                                                                <div className="text-sm text-secondary">
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
                                                                                        intentContext:
                                                                                            ProductIntentContext.SURVEY_RESUMED,
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
                                                                    onClick={() => {
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: { archived: false },
                                                                            intentContext:
                                                                                ProductIntentContext.SURVEY_UNARCHIVED,
                                                                        })
                                                                    }}
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
                                                                                <div className="text-sm text-secondary">
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
                                                                                        intentContext:
                                                                                            ProductIntentContext.SURVEY_ARCHIVED,
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
                                                                            <div className="text-sm text-secondary">
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
