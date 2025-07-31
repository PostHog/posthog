import './SurveyView.scss'

import { IconGraph, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useEffect, useState } from 'react'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { SurveyQuestionVisualization } from 'scenes/surveys/components/question-visualizations/SurveyQuestionVisualization'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SurveyNoResponsesBanner } from 'scenes/surveys/SurveyNoResponsesBanner'
import { SurveyOverview } from 'scenes/surveys/SurveyOverview'
import { SurveyResponseFilters } from 'scenes/surveys/SurveyResponseFilters'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { SurveyStatsSummary } from 'scenes/surveys/SurveyStatsSummary'

import { Query } from '~/queries/Query/Query'
import {
    ActivityScope,
    PropertyFilterType,
    PropertyOperator,
    SurveyEventName,
    SurveyEventProperties,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { organizationLogic } from 'scenes/organizationLogic'
import { DuplicateToProjectModal, DuplicateToProjectTrigger } from 'scenes/surveys/DuplicateToProjectModal'
import {
    ScenePanel,
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
} from '~/layout/scenes/SceneLayout'
import { SurveysDisabledBanner } from './SurveySettings'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
const RESOURCE_TYPE = 'survey'

export function SurveyView({ id }: { id: string }): JSX.Element {
    const { survey, surveyLoading } = useValues(surveyLogic)
    const {
        editingSurvey,
        updateSurvey,
        launchSurvey,
        stopSurvey,
        archiveSurvey,
        resumeSurvey,
        duplicateSurvey,
        setIsDuplicateToProjectModalOpen,
    } = useActions(surveyLogic)
    const { deleteSurvey } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1
    const { showSurveysDisabledBanner } = useValues(surveysLogic)

    const [tabKey, setTabKey] = useState(survey.start_date ? 'results' : 'overview')
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]
    useEffect(() => {
        if (survey.start_date) {
            setTabKey('results')
        } else {
            setTabKey('overview')
        }
    }, [survey.start_date])

    return (
        <div>
            {surveyLoading ? (
                <LemonSkeleton />
            ) : (
                <>
                    <PageHeader
                        buttons={
                            <div className="flex gap-2 items-center">
                                <LemonButton
                                    size="small"
                                    type={!newSceneLayout ? 'secondary' : undefined}
                                    id="surveys-page-feedback-button"
                                    tooltip={newSceneLayout ? 'Have any questions or feedback?' : undefined}
                                >
                                    {!newSceneLayout ? <>Have any questions or feedback?</> : <>Feedback</>}
                                </LemonButton>

                                {!newSceneLayout && (
                                    <>
                                        <More
                                            overlay={
                                                <>
                                                    <>
                                                        <LemonButton
                                                            data-attr="edit-survey"
                                                            fullWidth
                                                            onClick={() => editingSurvey(true)}
                                                        >
                                                            Edit
                                                        </LemonButton>
                                                        {!hasMultipleProjects ? (
                                                            <LemonButton
                                                                data-attr="duplicate-survey"
                                                                fullWidth
                                                                onClick={duplicateSurvey}
                                                            >
                                                                Duplicate
                                                            </LemonButton>
                                                        ) : (
                                                            <DuplicateToProjectTrigger />
                                                        )}

                                                        <LemonDivider />
                                                    </>
                                                    {survey.end_date && !survey.archived && (
                                                        <LemonButton
                                                            data-attr="archive-survey"
                                                            onClick={() => {
                                                                LemonDialog.open({
                                                                    title: 'Archive this survey?',
                                                                    content: (
                                                                        <div className="text-sm text-secondary">
                                                                            This action will remove the survey from your
                                                                            active surveys list. It can be restored at
                                                                            any time.
                                                                        </div>
                                                                    ),
                                                                    primaryButton: {
                                                                        children: 'Archive',
                                                                        type: 'primary',
                                                                        onClick: () => archiveSurvey(),
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
                                                            Archive
                                                        </LemonButton>
                                                    )}
                                                    <LemonButton
                                                        status="danger"
                                                        data-attr="delete-survey"
                                                        fullWidth
                                                        onClick={() => {
                                                            LemonDialog.open({
                                                                title: 'Delete this survey?',
                                                                content: (
                                                                    <div className="text-sm text-secondary">
                                                                        This action cannot be undone. All survey data
                                                                        will be permanently removed.
                                                                    </div>
                                                                ),
                                                                primaryButton: {
                                                                    children: 'Delete',
                                                                    type: 'primary',
                                                                    onClick: () => deleteSurvey(id),
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
                                                        Delete survey
                                                    </LemonButton>
                                                </>
                                            }
                                        />
                                        <LemonDivider vertical />
                                    </>
                                )}
                                {newSceneLayout && (
                                    <LemonButton
                                        data-attr="edit-survey"
                                        onClick={() => editingSurvey(true)}
                                        type="secondary"
                                    >
                                        Edit
                                    </LemonButton>
                                )}
                                {!survey.start_date ? (
                                    <LemonButton
                                        type="primary"
                                        data-attr="launch-survey"
                                        disabledReason={
                                            showSurveysDisabledBanner && survey.type !== SurveyType.API
                                                ? 'Please enable surveys in the banner below before launching'
                                                : undefined
                                        }
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Launch this survey?',
                                                content: (
                                                    <div className="text-sm text-secondary">
                                                        The survey will immediately start displaying to users matching
                                                        the display conditions.
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Launch',
                                                    type: 'primary',
                                                    onClick: () => launchSurvey(),
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
                                        Launch
                                    </LemonButton>
                                ) : survey.end_date && !survey.archived ? (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Resume this survey?',
                                                content: (
                                                    <div className="text-sm text-secondary">
                                                        Once resumed, the survey will be visible to your users again.
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Resume',
                                                    type: 'primary',
                                                    onClick: () => resumeSurvey(),
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
                                        Resume
                                    </LemonButton>
                                ) : (
                                    !survey.archived && (
                                        <LemonButton
                                            data-attr="stop-survey"
                                            type="secondary"
                                            status="danger"
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Stop this survey?',
                                                    content: (
                                                        <div className="text-sm text-secondary">
                                                            The survey will no longer be displayed to users.
                                                        </div>
                                                    ),
                                                    primaryButton: {
                                                        children: 'Stop',
                                                        type: 'primary',
                                                        onClick: () => stopSurvey(),
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
                                            Stop
                                        </LemonButton>
                                    )
                                )}
                            </div>
                        }
                        caption={
                            <>
                                {survey && !!survey.description && (
                                    <EditableField
                                        multiline
                                        name="description"
                                        markdown
                                        value={survey.description || ''}
                                        placeholder="Description (optional)"
                                        onSave={(value) =>
                                            updateSurvey({
                                                id: id,
                                                description: value,
                                                intentContext: ProductIntentContext.SURVEY_EDITED,
                                            })
                                        }
                                        saveOnBlur={true}
                                        compactButtons
                                    />
                                )}
                            </>
                        }
                    />
                    <ScenePanel>
                        <ScenePanelCommonActions>
                            {surveyLoading ? (
                                <WrappingLoadingSkeleton>
                                    <ButtonPrimitive aria-hidden>X</ButtonPrimitive>
                                </WrappingLoadingSkeleton>
                            ) : (
                                <SceneCommonButtons
                                    dataAttrKey={RESOURCE_TYPE}
                                    duplicate={{
                                        onClick: () => {
                                            if (hasMultipleProjects) {
                                                setIsDuplicateToProjectModalOpen(true)
                                            } else {
                                                duplicateSurvey()
                                            }
                                        },
                                    }}
                                />
                            )}
                        </ScenePanelCommonActions>
                        <ScenePanelMetaInfo>
                            <SceneFile dataAttrKey={RESOURCE_TYPE} />
                        </ScenePanelMetaInfo>
                        <ScenePanelDivider />
                        <ScenePanelActions>
                            <ButtonPrimitive
                                menuItem
                                variant="danger"
                                data-attr={`${RESOURCE_TYPE}-delete`}
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Delete this survey?',
                                        content: (
                                            <div className="text-sm text-secondary">
                                                This action cannot be undone. All survey data will be permanently
                                                removed.
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Delete',
                                            type: 'primary',
                                            onClick: () => deleteSurvey(id),
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
                                <IconTrash />
                                Delete survey
                            </ButtonPrimitive>
                        </ScenePanelActions>
                    </ScenePanel>
                    <SurveysDisabledBanner />
                    <LemonTabs
                        activeKey={tabKey}
                        onChange={(key) => setTabKey(key)}
                        tabs={[
                            survey.start_date
                                ? {
                                      content: (
                                          <div>
                                              <SurveyResult />
                                          </div>
                                      ),
                                      key: 'results',
                                      label: 'Results',
                                  }
                                : null,
                            {
                                content: <SurveyOverview />,
                                key: 'overview',
                                label: 'Overview',
                            },
                            {
                                key: 'notifications',
                                label: 'Notifications',
                                content: (
                                    <div>
                                        <p>Get notified whenever a survey result is submitted</p>
                                        <LinkedHogFunctions
                                            type="destination"
                                            subTemplateIds={['survey-response']}
                                            forceFilterGroups={[
                                                {
                                                    events: [
                                                        {
                                                            id: SurveyEventName.SENT,
                                                            type: 'events',
                                                            properties: [
                                                                {
                                                                    key: SurveyEventProperties.SURVEY_ID,
                                                                    type: PropertyFilterType.Event,
                                                                    value: id,
                                                                    operator: PropertyOperator.Exact,
                                                                },
                                                            ],
                                                        },
                                                    ],
                                                },
                                            ]}
                                        />
                                    </div>
                                ),
                            },
                            {
                                label: 'History',
                                key: 'History',
                                content: <ActivityLog scope={ActivityScope.SURVEY} id={survey.id} />,
                            },
                        ]}
                    />
                    {hasMultipleProjects && <DuplicateToProjectModal />}
                </>
            )}
        </div>
    )
}

function SurveyResponsesByQuestionV2(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    return (
        <div className="flex flex-col gap-2">
            {survey.questions.map((question, i) => {
                if (!question.id || question.type === SurveyQuestionType.Link) {
                    return null
                }
                return (
                    <div key={question.id} className="flex flex-col gap-2">
                        <SurveyQuestionVisualization question={question} questionIndex={i} />
                        <LemonDivider />
                    </div>
                )
            })}
        </div>
    )
}

export function SurveyResult({ disableEventsTable }: { disableEventsTable?: boolean }): JSX.Element {
    const { dataTableQuery, surveyLoading, surveyAsInsightURL, isAnyResultsLoading, processedSurveyStats } =
        useValues(surveyLogic)

    const atLeastOneResponse = !!processedSurveyStats?.[SurveyEventName.SENT].total_count

    return (
        <div className="deprecated-space-y-4">
            <SurveyResponseFilters />
            <SurveyStatsSummary />
            {isAnyResultsLoading || atLeastOneResponse ? (
                <>
                    <SurveyResponsesByQuestionV2 />
                    <LemonButton
                        type="primary"
                        data-attr="survey-results-explore"
                        icon={<IconGraph />}
                        to={surveyAsInsightURL}
                        className="max-w-40"
                    >
                        Explore results
                    </LemonButton>
                    {!disableEventsTable &&
                        (surveyLoading ? (
                            <LemonSkeleton />
                        ) : (
                            <div className="survey-table-results">
                                <Query query={dataTableQuery} />
                            </div>
                        ))}
                </>
            ) : (
                <SurveyNoResponsesBanner type="survey" />
            )}
        </div>
    )
}
