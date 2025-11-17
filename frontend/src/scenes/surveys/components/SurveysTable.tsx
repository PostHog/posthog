import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonDialog, LemonDivider, LemonInput, LemonSelect, LemonTable, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { MemberSelect } from 'lib/components/MemberSelect'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { cn } from 'lib/utils/css-classes'
import { ProductIntentContext } from 'lib/utils/product-intents'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SurveyStatusTag } from 'scenes/surveys/components/SurveyStatusTag'
import { SurveysEmptyState } from 'scenes/surveys/components/empty-state/SurveysEmptyState'
import { SURVEY_TYPE_LABEL_MAP, SurveyQuestionLabel } from 'scenes/surveys/constants'
import { SurveysTabs, surveysLogic } from 'scenes/surveys/surveysLogic'
import { isSurveyRunning } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, Survey } from '~/types'

export function SurveysTable(): JSX.Element {
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

    const { deleteSurvey, updateSurvey, setSearchTerm, setSurveysFilters, loadNextPage, loadNextSearchPage } =
        useActions(surveysLogic)

    const shouldShowEmptyState = !dataLoading && surveys.length === 0

    if (shouldShowEmptyState) {
        return <SurveysEmptyState numOfSurveys={surveys.length} />
    }

    return (
        <>
            <div>
                <div className={cn('flex flex-wrap gap-2 justify-between mb-0')}>
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
                emptyState={tab === SurveysTabs.Active ? 'No surveys. Create a new survey?' : 'No surveys found'}
                loading={dataLoading}
                footer={
                    (searchTerm ? hasNextSearchPage : hasNextPage) && (
                        <div className="flex justify-center p-1">
                            <LemonButton
                                onClick={searchTerm ? loadNextSearchPage : loadNextPage}
                                className="min-w-full text-center"
                                disabledReason={dataLoading ? 'Loading surveys' : ''}
                            >
                                <span className="flex-1 text-center">{dataLoading ? 'Loading...' : 'Load more'}</span>
                            </LemonButton>
                        </div>
                    )
                }
                columns={[
                    {
                        dataIndex: 'name',
                        title: 'Name',
                        render: function RenderName(_, survey) {
                            return <LemonTableLink to={urls.survey(survey.id)} title={stringWithWBR(survey.name, 17)} />
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
                              createdAtColumn<Survey>() as LemonTableColumn<Survey, keyof Survey | undefined>,
                              {
                                  title: 'Status',
                                  width: 100,
                                  render: function Render(_: any, survey: Survey) {
                                      return <SurveyStatusTag survey={survey} />
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
                                                onClick={() => router.actions.push(urls.survey(survey.id))}
                                            >
                                                View
                                            </LemonButton>
                                            {!survey.start_date && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.Survey}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    userAccessLevel={survey.user_access_level}
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() =>
                                                            LemonDialog.open({
                                                                title: 'Launch this survey?',
                                                                content: (
                                                                    <div className="text-sm text-secondary">
                                                                        The survey will immediately start displaying to
                                                                        users matching the display conditions.
                                                                    </div>
                                                                ),
                                                                primaryButton: {
                                                                    children: 'Launch',
                                                                    type: 'primary',
                                                                    onClick: () => {
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                start_date: dayjs().toISOString(),
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
                                                </AccessControlAction>
                                            )}
                                            {isSurveyRunning(survey) && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.Survey}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    userAccessLevel={survey.user_access_level}
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: 'Stop this survey?',
                                                                content: (
                                                                    <div className="text-sm text-secondary">
                                                                        The survey will no longer be visible to your
                                                                        users.
                                                                    </div>
                                                                ),
                                                                primaryButton: {
                                                                    children: 'Stop',
                                                                    type: 'primary',
                                                                    onClick: () => {
                                                                        updateSurvey({
                                                                            id: survey.id,
                                                                            updatePayload: {
                                                                                end_date: dayjs().toISOString(),
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
                                                </AccessControlAction>
                                            )}
                                            {survey.end_date && !survey.archived && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.Survey}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    userAccessLevel={survey.user_access_level}
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: 'Resume this survey?',
                                                                content: (
                                                                    <div className="text-sm text-secondary">
                                                                        Once resumed, the survey will be visible to your
                                                                        users again.
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
                                                </AccessControlAction>
                                            )}
                                            <LemonDivider />
                                            {survey.end_date && survey.archived && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.Survey}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    userAccessLevel={survey.user_access_level}
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            updateSurvey({
                                                                id: survey.id,
                                                                updatePayload: { archived: false },
                                                                intentContext: ProductIntentContext.SURVEY_UNARCHIVED,
                                                            })
                                                        }}
                                                    >
                                                        Unarchive
                                                    </LemonButton>
                                                </AccessControlAction>
                                            )}
                                            {survey.end_date && !survey.archived && (
                                                <AccessControlAction
                                                    resourceType={AccessControlResourceType.Survey}
                                                    minAccessLevel={AccessControlLevel.Editor}
                                                    userAccessLevel={survey.user_access_level}
                                                >
                                                    <LemonButton
                                                        fullWidth
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: 'Archive this survey?',
                                                                content: (
                                                                    <div className="text-sm text-secondary">
                                                                        This action will remove the survey from your
                                                                        active surveys list. It can be restored at any
                                                                        time.
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
                                                </AccessControlAction>
                                            )}
                                            <AccessControlAction
                                                resourceType={AccessControlResourceType.Survey}
                                                minAccessLevel={AccessControlLevel.Editor}
                                                userAccessLevel={survey.user_access_level}
                                            >
                                                <LemonButton
                                                    status="danger"
                                                    onClick={() => {
                                                        LemonDialog.open({
                                                            title: 'Delete this survey?',
                                                            content: (
                                                                <div className="text-sm text-secondary">
                                                                    This action cannot be undone. All survey data will
                                                                    be permanently removed.
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
                                            </AccessControlAction>
                                        </>
                                    }
                                />
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
