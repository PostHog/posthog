import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonDivider } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { getSurveyStatusTagType } from 'scenes/surveys/components/SurveyStatusTag'
import { SurveyDisplaySummary } from 'scenes/surveys/Survey'
import { SurveyAppearancePreview } from 'scenes/surveys/SurveyAppearancePreview'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { SURVEY_NOTEBOOK_WIDGET_VIEWS, SurveyNotebookWidgetAttributes } from 'scenes/surveys/surveyNotebookWidgetViews'
import { getSurveyStatus } from 'scenes/surveys/surveysLogic'
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
    const { insertAfter, setActions, setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

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
        const status = getSurveyStatus(survey)
        setTitleStatus({
            label: status,
            type: getSurveyStatusTagType(status),
        })
        // oxlint-disable-next-line exhaustive-deps
    }, [survey.name, survey.start_date, survey.end_date])

    return null
}

const Component = ({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element => {
    const { id } = attributes
    const { survey, targetingFlagFilters, surveyMissing } = useValues(surveyLogic({ id }))
    const { expanded } = useValues(notebookNodeLogic)

    if (surveyMissing) {
        return <NotFound object="survey" />
    }

    return (
        <BindLogic logic={surveyLogic} props={{ id }}>
            <div>
                {expanded ? (
                    <>
                        {survey.description && (
                            <>
                                <div className="p-2">{survey.description}</div>
                                <LemonDivider className="my-0" />
                            </>
                        )}
                        {!survey.start_date ? (
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
                        ) : (
                            <div className="p-2">
                                <SurveyResult disableEventsTable />
                            </div>
                        )}
                    </>
                ) : null}
            </div>
        </BindLogic>
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
