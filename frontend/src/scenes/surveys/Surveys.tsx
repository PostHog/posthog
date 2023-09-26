import { LemonButton, LemonTable, LemonDivider, Link, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { getSurveyStatus, surveysLogic } from './surveysLogic'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ProductKey, ProgressStatus, Survey } from '~/types'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { userLogic } from 'scenes/userLogic'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { dayjs } from 'lib/dayjs'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { teamLogic } from 'scenes/teamLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { IconSettings } from 'lib/lemon-ui/icons'
import { openSurveysSettingsDialog } from './SurveySettings'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
}

export enum SurveysTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export function Surveys(): JSX.Element {
    const { nonArchivedSurveys, archivedSurveys, surveys, surveysLoading } = useValues(surveysLogic)
    const { deleteSurvey, updateSurvey } = useActions(surveysLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { currentTeam } = useValues(teamLogic)
    const surveysPopupDisabled = currentTeam && !currentTeam?.surveys_opt_in

    const [tab, setSurveyTab] = useState(SurveysTabs.All)
    const shouldShowEmptyState = !surveysLoading && surveys.length === 0

    return (
        <div className="mt-10">
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Surveys
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                buttons={
                    <LemonButton type="primary" to={urls.survey('new')} data-attr="new-survey">
                        New survey
                    </LemonButton>
                }
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setSurveyTab(newTab)}
                tabs={[
                    { key: SurveysTabs.All, label: 'All surveys' },
                    { key: SurveysTabs.Archived, label: 'Archived surveys' },
                ]}
            />
            {featureFlags[FEATURE_FLAGS.SURVEYS_SITE_APP_DEPRECATION] && (
                <div className="space-y-2">
                    <VersionCheckerBanner />

                    {surveysPopupDisabled ? (
                        <LemonBanner
                            type="info"
                            action={{
                                type: 'secondary',
                                icon: <IconSettings />,
                                onClick: () => openSurveysSettingsDialog(),
                                children: 'Configure',
                            }}
                        >
                            Survey popups are currently disabled for this project.
                        </LemonBanner>
                    ) : null}
                </div>
            )}
            {surveysLoading ? (
                <LemonSkeleton />
            ) : (
                <>
                    {(shouldShowEmptyState || !user?.has_seen_product_intro_for?.[ProductKey.SURVEYS]) && (
                        <ProductIntroduction
                            productName={'Surveys'}
                            thingName={'survey'}
                            description={
                                'Use surveys to gather qualitative feedback from your users on new or existing features.'
                            }
                            action={() => router.actions.push(urls.survey('new'))}
                            isEmpty={surveys.length === 0}
                            productKey={ProductKey.SURVEYS}
                        />
                    )}
                    {!shouldShowEmptyState && (
                        <LemonTable
                            className="mt-6"
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
                                // TODO: add responses count later
                                // {
                                //     title: 'Responses',
                                //     render: function RenderResponses() {
                                //         // const responsesCount = getResponsesCount(survey)
                                //         return <div>{0}</div>
                                //     },
                                // },
                                {
                                    dataIndex: 'type',
                                    title: 'Type',
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
                                                                onClick={() =>
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: {
                                                                            end_date: dayjs().toISOString(),
                                                                        },
                                                                    })
                                                                }
                                                            >
                                                                Stop survey
                                                            </LemonButton>
                                                        )}
                                                        {survey.end_date && !survey.archived && (
                                                            <LemonButton
                                                                status="stealth"
                                                                fullWidth
                                                                onClick={() =>
                                                                    updateSurvey({
                                                                        id: survey.id,
                                                                        updatePayload: { end_date: null },
                                                                    })
                                                                }
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
                            dataSource={tab === SurveysTabs.Archived ? archivedSurveys : nonArchivedSurveys}
                            defaultSorting={{
                                columnKey: 'created_at',
                                order: -1,
                            }}
                            nouns={['survey', 'surveys']}
                            data-attr="surveys-table"
                            emptyState="No surveys. Create a new survey?"
                        />
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
        <LemonTag type={statusColors[status]} style={{ fontWeight: 600 }}>
            {status.toUpperCase()}
        </LemonTag>
    )
}
