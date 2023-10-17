import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { FeatureFlagBasicType, NotebookNodeType, Survey, SurveyQuestionType } from '~/types'
import { BindLogic, useActions, useValues } from 'kea'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from './notebookNodeLogic'
import { JSONContent, NotebookNodeProps } from '../Notebook/utils'
import { buildFlagContent } from './NotebookNodeFlag'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { defaultSurveyAppearance } from 'scenes/surveys/constants'
import { StatusTag } from 'scenes/surveys/Surveys'
import { SurveyResult } from 'scenes/surveys/SurveyView'
import { SurveyAppearance } from 'scenes/surveys/SurveyAppearance'
import { SurveyReleaseSummary } from 'scenes/surveys/Survey'
import { useEffect } from 'react'
import { NotFound } from 'lib/components/NotFound'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeSurveyAttributes>): JSX.Element => {
    const { id } = attributes
    const { survey, surveyLoading, hasTargetingFlag, surveyMissing } = useValues(surveyLogic({ id }))
    const { expanded, nextNode } = useValues(notebookNodeLogic)
    const { insertAfter, setActions, setTitlePlaceholder } = useActions(notebookNodeLogic)

    useEffect(() => {
        setActions([
            survey.linked_flag
                ? {
                      text: 'View linked flag',
                      onClick: () => {
                          if (nextNode?.type.name !== NotebookNodeType.FeatureFlag) {
                              insertAfter(buildFlagContent((survey.linked_flag as FeatureFlagBasicType).id))
                          }
                      },
                  }
                : undefined,
        ])
    }, [survey])

    useEffect(() => {
        setTitlePlaceholder(survey.name ? `Survey: ${survey.name}` : 'Survey')
    }, [survey.name])

    if (surveyMissing) {
        return <NotFound object={'survey'} />
    }

    return (
        <div>
            <BindLogic logic={surveyLogic} props={{ id }}>
                <div className="flex items-center gap-2 p-3">
                    <IconSurveys className="text-lg" />
                    {surveyLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{survey.name}</span>
                            {/* survey has to exist in notebooks */}
                            <StatusTag survey={survey as Survey} />
                        </>
                    )}
                </div>

                {expanded ? (
                    <>
                        {survey.description && (
                            <>
                                <LemonDivider className="my-0" />
                                <span className="p-2">{survey.description}</span>
                            </>
                        )}
                        {!survey.start_date ? (
                            <>
                                <LemonDivider className="my-0" />
                                <div className="p-2">
                                    <SurveyReleaseSummary id={id} survey={survey} hasTargetingFlag={hasTargetingFlag} />

                                    <div className="w-full flex flex-col items-center">
                                        <SurveyAppearance
                                            type={survey.questions[0].type}
                                            surveyQuestionItem={survey.questions[0]}
                                            appearance={survey.appearance || defaultSurveyAppearance}
                                            question={survey.questions[0].question}
                                            description={survey.questions[0].description}
                                            link={
                                                survey.questions[0].type === SurveyQuestionType.Link
                                                    ? survey.questions[0].link
                                                    : undefined
                                            }
                                        />
                                    </div>
                                </div>
                            </>
                        ) : (
                            <>
                                {/* show results when the survey is running */}
                                <LemonDivider className="my-0" />
                                <div className="p-2">
                                    <SurveyResult disableEventsTable />
                                </div>
                            </>
                        )}
                    </>
                ) : null}
                {/* 
                <LemonDivider className="my-0" />
                <div className="p-2 mr-1 flex justify-end gap-2">
                    {survey.linked_flag && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconFlag />}
                            onClick={(e) => {
                                e.stopPropagation()

                                if (nextNode?.type.name !== NotebookNodeType.FeatureFlag) {
                                    insertAfter(buildFlagContent((survey.linked_flag as FeatureFlagBasicType).id))
                                }
                            }}
                            disabledReason={
                                nextNode?.type.name === NotebookNodeType.FeatureFlag &&
                                'Feature flag already exists below'
                            }
                        >
                            View Linked Flag
                        </LemonButton>
                    )}
                </div> */}
            </BindLogic>
        </div>
    )
}

type NotebookNodeSurveyAttributes = {
    id: string
}

export const NotebookNodeSurvey = createPostHogWidgetNode<NotebookNodeSurveyAttributes>({
    nodeType: NotebookNodeType.Survey,
    titlePlaceholder: 'Survey',
    Component,
    heightEstimate: '3rem',
    href: (attrs) => urls.survey(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.survey('') + '(.+)',
        getAttributes: async (match) => {
            return { id: match[1] }
        },
    },
})

export function buildSurveyContent(id: string): JSONContent {
    return {
        type: NotebookNodeType.Survey,
        attrs: { id },
    }
}
