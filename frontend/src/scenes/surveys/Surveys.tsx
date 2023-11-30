import {
    LemonButton,
    LemonButtonWithSideAction,
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
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { dayjs } from 'lib/dayjs'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey, ProgressStatus, Survey } from '~/types'

import { SurveyQuestionLabel } from './constants'
import { openSurveysSettingsDialog } from './SurveySettings'
import { getSurveyStatus, surveysLogic } from './surveysLogic'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
}

export enum SurveysTabs {
    Active = 'active',
    Yours = 'yours',
    Archived = 'archived',
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
        uniqueCreators,
        showSurveysDisabledBanner,
    } = useValues(surveysLogic)

    const { deleteSurvey, updateSurvey, setSearchTerm, setSurveysFilters } = useActions(surveysLogic)

    const { user } = useValues(userLogic)

    const [tab, setSurveyTab] = useState(SurveysTabs.Active)
    const shouldShowEmptyState = !surveysLoading && surveys.length === 0

    return (
        <div>
            <PageHeader
                title="Surveys"
                buttons={
                    <>
                        <LemonButtonWithSideAction
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
                        </LemonButtonWithSideAction>
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
                onChange={(newTab) => {
                    setSurveyTab(newTab)
                    setSurveysFilters({ ...filters, archived: newTab === SurveysTabs.Archived })
                }}
                tabs={[
                    { key: SurveysTabs.Active, label: 'Active' },
                    { key: SurveysTabs.Archived, label: 'Archived' },
                ]}
            />
            <div className="space-y-2">
                <VersionCheckerBanner minVersionAccepted="1.83.0" />

                {showSurveysDisabledBanner ? (
                    <LemonBanner
                        type="warning"
                        action={{
                            type: 'secondary',
                            icon: <IconSettings />,
                            onClick: () => openSurveysSettingsDialog(),
                            children: 'Configure',
                        }}
                        className="mb-2"
                    >
                        Survey popovers are currently disabled for this project but there are active surveys running.
                        Re-enable them in the settings.
                    </LemonBanner>
                ) : null}
            </div>

            <>
                {(shouldShowEmptyState || !user?.has_seen_product_intro_for?.[ProductKey.SURVEYS]) && (
                    <ProductIntroduction
                        productName={'Surveys'}
                        thingName={'survey'}
                        description={
                            'Use surveys to gather qualitative feedback from your users on new or existing features.'
                        }
                        action={() => router.actions.push(urls.surveyTemplates())}
                        isEmpty={surveys.length === 0}
                        productKey={ProductKey.SURVEYS}
                    />
                )}
                {!shouldShowEmptyState && (
                    <>
                        <div>
                            <div className="flex justify-between mb-4">
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
                                    <LemonSelect
                                        onChange={(user) => {
                                            setSurveysFilters({ created_by: user })
                                        }}
                                        options={uniqueCreators}
                                        value={filters.created_by}
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
                                            <>
                                                <Link to={urls.survey(survey.id)} className="row-name">
                                                    {stringWithWBR(survey.name, 17)}
                                                </Link>
                                            </>
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
                                                            status="stealth"
                                                            fullWidth
                                                            onClick={() => router.actions.push(urls.survey(survey.id))}
                                                        >
                                                            View
                                                        </LemonButton>
                                                        {!survey.start_date && (
                                                            <LemonButton
                                                                status="stealth"
                                                                fullWidth
                                                                onClick={() =>
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: {
                                                                            start_date: dayjs().toISOString(),
                                                                        },
                                                                    })
                                                                }
                                                            >
                                                                Launch survey
                                                            </LemonButton>
                                                        )}
                                                        {survey.start_date && !survey.end_date && (
                                                            <LemonButton
                                                                status="stealth"
                                                                fullWidth
                                                                onClick={() => {
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: {
                                                                            end_date: dayjs().toISOString(),
                                                                        },
                                                                    })
                                                                }}
                                                            >
                                                                Stop survey
                                                            </LemonButton>
                                                        )}
                                                        {survey.end_date && !survey.archived && (
                                                            <LemonButton
                                                                status="stealth"
                                                                fullWidth
                                                                onClick={() => {
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: { end_date: null },
                                                                    })
                                                                }}
                                                            >
                                                                Resume survey
                                                            </LemonButton>
                                                        )}
                                                        <LemonDivider />
                                                        {survey.end_date && survey.archived && (
                                                            <LemonButton
                                                                status="stealth"
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
                                                                status="stealth"
                                                                fullWidth
                                                                onClick={() =>
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: { archived: true },
                                                                    })
                                                                }
                                                            >
                                                                Archive
                                                            </LemonButton>
                                                        )}
                                                        <LemonButton
                                                            status="danger"
                                                            onClick={() => deleteSurvey(survey.id)}
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
        <LemonTag type={statusColors[status]} style={{ fontWeight: 600 }}>
            {status.toUpperCase()}
        </LemonTag>
    )
}
