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
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'
import { isSurveyRunning } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { useActions as useTeamActions } from 'kea'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityScope, ProductKey, ProgressStatus, Survey } from '~/types'

import { SURVEY_TYPE_LABEL_MAP, SurveyQuestionLabel } from './constants'
import { SurveysDisabledBanner, SurveySettings } from './SurveySettings'
import { getSurveyStatus, surveysLogic, SurveysTabs } from './surveysLogic'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
    settingSectionId: 'environment-surveys',
}

export function Surveys(): JSX.Element {
    const {
        surveys,
        surveysLoading: dataLoading,
        surveysResponsesCount,
        surveysResponsesCountLoading,
        searchTerm,
        filters
    } = useValues(surveysLogic)

    const { deleteSurvey, updateSurvey, setSearchTerm, setSurveysFilters } = useActions(surveysLogic)

    const { addProductIntent } = useActions(teamLogic)
    const { user } = useValues(userLogic)
    const shouldShowEmptyState = !dataLoading && surveys.length === 0

    return (
        <div>
            <PageHeader
                buttons={
                    <>
                        <LemonButton size="small" type="secondary" id="surveys-page-feedback-button">
                            Have any questions or feedback?
                        </LemonButton>
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
                activeKey={SurveysTabs.Active}
                onChange={(newTab) => {}}
                tabs={[
                    { key: SurveysTabs.Active, label: 'Active' },
                    { key: SurveysTabs.Archived, label: 'Archived' },
                    { key: SurveysTabs.Notifications, label: 'Notifications' },
                    { key: SurveysTabs.History, label: 'History' },
                    { key: SurveysTabs.Settings, label: 'Settings' },
                ]}
            />
            {/* {tab === SurveysTabs.Settings && <SurveySettings />} */}
            {/* {tab === SurveysTabs.Notifications && (
                <>
                    <p>Get notified whenever a survey result is submitted</p>
                    <LinkedHogFunctions type="destination" subTemplateIds={['survey-response']} />
                </>
            )} */}

            {/* {tab === SurveysTabs.History && <ActivityLog scope={ActivityScope.SURVEY} />} */}

            {(SurveysTabs.Active || SurveysTabs.Archived) && (
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
                                dataSource={surveys}
                                defaultSorting={{
                                    columnKey: 'created_at',
                                    order: -1,
                                }}
                                rowKey="name"
                                nouns={['survey', 'surveys']}
                                data-attr="surveys-table"
                                emptyState={
                                    SurveysTabs.Active ? 'No surveys. Create a new survey?' : 'No surveys found'
                                }
                                loading={dataLoading}
                                footer={
                                    (searchTerm ? loadNextSearchPage : loadNextPage) && (
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
                                                                    onClick={() => {
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                start_date:
                                                                                    dayjs().toISOString(),
                                                                            },
                                                                        })
                                                                        addProductIntent({
                                                                            product_type: ProductKey.SURVEYS,
                                                                            intent_context: ProductIntentContext.SURVEY_LAUNCHED,
                                                                            metadata: { surveyId: survey.id },
                                                                        })
                                                                    }}
                                                                >
                                                                    Launch survey
                                                                </LemonButton>
                                                            )}
                                                            {isSurveyRunning(survey) && (
                                                                <LemonButton
                                                                    fullWidth
                                                                    onClick={() => {
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                end_date:
                                                                                    dayjs().toISOString(),
                                                                            },
                                                                        })
                                                                        addProductIntent({
                                                                            product_type: ProductKey.SURVEYS,
                                                                            intent_context: ProductIntentContext.SURVEY_COMPLETED,
                                                                            metadata: { surveyId: survey.id },
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
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                end_date: null,
                                                                            },
                                                                        })
                                                                        addProductIntent({
                                                                            product_type: ProductKey.SURVEYS,
                                                                            intent_context: ProductIntentContext.SURVEY_RESUMED,
                                                                            metadata: { surveyId: survey.id },
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
                                                                            updatePayload: {
                                                                                archived: false,
                                                                            },
                                                                        })
                                                                        addProductIntent({
                                                                            product_type: ProductKey.SURVEYS,
                                                                            intent_context: ProductIntentContext.SURVEY_UNARCHIVED,
                                                                            metadata: { surveyId: survey.id },
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
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                archived: true,
                                                                            },
                                                                        })
                                                                        addProductIntent({
                                                                            product_type: ProductKey.SURVEYS,
                                                                            intent_context: ProductIntentContext.SURVEY_ARCHIVED,
                                                                            metadata: { surveyId: survey.id },
                                                                        })
                                                                    }}
                                                                >
                                                                    Archive
                                                                </LemonButton>
                                                            )}
                                                            <LemonButton
                                                                status="danger"
                                                                onClick={() => {
                                                                    deleteSurvey(survey.id)
                                                                    addProductIntent({
                                                                        product_type: ProductKey.SURVEYS,
                                                                        intent_context: ProductIntentContext.SURVEY_DELETED,
                                                                        metadata: { surveyId: survey.id },
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
