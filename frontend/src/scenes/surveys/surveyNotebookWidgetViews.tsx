import { BindLogic, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { NEW_SURVEY, SURVEY_TYPE_LABEL_MAP } from './constants'
import { SurveyDisplaySummary } from './Survey'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { surveyLogic } from './surveyLogic'
import { SurveyResult } from './SurveyView'

export type SurveyNotebookWidgetAttributes = {
    id: string
    view?: string
}

function SurveyWidgetLoading(): JSX.Element {
    return (
        <div className="flex items-center gap-2 p-3">
            <IconSurveys className="text-lg" />
            <LemonSkeleton className="h-6 flex-1" />
        </div>
    )
}

function SurveyCompactSummary({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { survey, surveyLoading, surveyMissing } = useValues(surveyLogic({ id }))

    if (surveyMissing) {
        return <NotFound object="survey" />
    }
    if (surveyLoading && survey.id === NEW_SURVEY.id) {
        return <SurveyWidgetLoading />
    }

    const questionCount = survey.questions.length

    return (
        <BindLogic logic={surveyLogic} props={{ id }}>
            <div className="flex flex-wrap items-center gap-2 p-3">
                {survey.description ? (
                    <span className="min-w-48 flex-1 truncate text-xs text-secondary">{survey.description}</span>
                ) : (
                    <span className="min-w-48 flex-1 text-xs text-secondary">No description</span>
                )}
                <LemonTag type="muted">{SURVEY_TYPE_LABEL_MAP[survey.type]}</LemonTag>
                <span className="text-xs text-secondary">
                    {questionCount} {questionCount === 1 ? 'question' : 'questions'}
                </span>
            </div>
        </BindLogic>
    )
}

function SurveyPreviewWidget({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { survey, surveyLoading, surveyMissing } = useValues(surveyLogic({ id }))

    if (surveyMissing) {
        return <NotFound object="survey" />
    }
    if (surveyLoading && survey.id === NEW_SURVEY.id) {
        return <SurveyWidgetLoading />
    }

    return (
        <BindLogic logic={surveyLogic} props={{ id }}>
            <div className="flex justify-center overflow-auto p-3">
                <SurveyAppearancePreview survey={survey} previewPageIndex={0} />
            </div>
        </BindLogic>
    )
}

function SurveyDisplayConditionsWidget({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { survey, surveyLoading, surveyMissing, targetingFlagFilters } = useValues(surveyLogic({ id }))

    if (surveyMissing) {
        return <NotFound object="survey" />
    }
    if (surveyLoading && survey.id === NEW_SURVEY.id) {
        return <SurveyWidgetLoading />
    }

    return (
        <BindLogic logic={surveyLogic} props={{ id }}>
            <div className="p-3">
                <SurveyDisplaySummary id={id} survey={survey} targetingFlagFilters={targetingFlagFilters} />
            </div>
        </BindLogic>
    )
}

function SurveyResultsWidget({ attributes }: NotebookNodeProps<SurveyNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { survey, surveyLoading, surveyMissing } = useValues(surveyLogic({ id }))

    if (surveyMissing) {
        return <NotFound object="survey" />
    }
    if (surveyLoading && survey.id === NEW_SURVEY.id) {
        return <SurveyWidgetLoading />
    }

    return (
        <BindLogic logic={surveyLogic} props={{ id }}>
            <div className="p-3">
                {survey.start_date ? (
                    <SurveyResult disableEventsTable />
                ) : (
                    <div className="text-sm text-secondary">Launch this survey to see results.</div>
                )}
            </div>
        </BindLogic>
    )
}

export const SURVEY_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<SurveyNotebookWidgetAttributes, 'Survey'>(
    'Survey',
    {
        summary: SurveyCompactSummary,
        preview: SurveyPreviewWidget,
        conditions: SurveyDisplayConditionsWidget,
        results: SurveyResultsWidget,
    }
)
