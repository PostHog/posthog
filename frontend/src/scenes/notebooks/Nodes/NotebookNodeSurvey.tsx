import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { SurveyStatusTag } from 'scenes/surveys/components/SurveyStatusTag'
import { SurveyDisplaySummary } from 'scenes/surveys/Survey'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SURVEY_NOTEBOOK_WIDGET_VIEWS, SurveyNotebookWidgetAttributes } from 'scenes/surveys/surveyNotebookWidgetViews'
import { SurveyResult } from 'scenes/surveys/SurveyView'
import { urls } from 'scenes/urls'

import { FeatureFlagBasicType } from '~/types'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { buildFlagContent } from './NotebookNodeFlag'
import { notebookNodeLogic } from './notebookNodeLogic'

function SurveyNotebookToolbar({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): null {
    const { id } = attributes
    const { survey } = useValues(surveyLogic({ id }))
    const { nextNode } = useValues(notebookNodeLogic)
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
        // oxlint-disable-next-line exhaustive-deps
    }, [survey])

    useEffect(() => {
        setTitlePlaceholder(survey.name || 'Survey')
        // oxlint-disable-next-line exhaustive-deps
    }, [survey.name])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { survey, surveyLoading, targetingFlagFilters, surveyMissing } = useValues(surveyLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    if (surveyMissing) {
        return <NotFound object="survey" />
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
                            <SurveyStatusTag survey={survey} />
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
                                    <SurveyDisplaySummary
                                        id={id}
                                        survey={survey}
                                        targetingFlagFilters={targetingFlagFilters}
                                    />

                                    <div className="w-full flex flex-col items-center">
                                        <SurveyAppearancePreview survey={survey} previewPageIndex={0} />
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
            </BindLogic>
        </div>
    )
}

export const NotebookNodeSurvey = createPostHogWidgetNode<SurveyNotebookWidgetAttributes>({
    nodeType: NotebookNodeType.Survey,
    titlePlaceholder: 'Survey',
    editableTitle: false,
    Component,
    ToolbarComponent: SurveyNotebookToolbar,
    heightEstimate: '3rem',
    href: (attrs) => urls.survey(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
        view: {},
    },
    defaultView: getNotebookWidgetDefaultView('Survey'),
    views: SURVEY_NOTEBOOK_WIDGET_VIEWS,
})

export function buildSurveyContent(id: string): JSONContent {
    return {
        type: NotebookNodeType.Survey,
        attrs: { id },
    }
}
