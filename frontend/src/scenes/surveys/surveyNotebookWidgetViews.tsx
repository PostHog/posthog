import { BindLogic, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { IconSurveys } from 'lib/lemon-ui/icons'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { NotebookNodeProps, PostHogWidgetViews } from 'scenes/notebooks/types'

import { SurveyStatusTag } from './components/SurveyStatusTag'
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
                <IconSurveys className="text-lg shrink-0" />
                <div className="flex min-w-48 flex-1 flex-col">
                    <span className="truncate font-semibold">{survey.name}</span>
                    {survey.description ? (
                        <span className="truncate text-xs text-secondary">{survey.description}</span>
                    ) : null}
                </div>
                <SurveyStatusTag survey={survey} />
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

export const SURVEY_NOTEBOOK_WIDGET_VIEWS = {
    'compact-summary': {
        label: 'Compact summary',
        description: 'Show the survey status, display mode, and question count',
        Component: SurveyCompactSummary,
    },
    preview: {
        label: 'Preview',
        description: 'Show the first page of the survey',
        Component: SurveyPreviewWidget,
    },
    'display-conditions': {
        label: 'Display conditions',
        description: 'Show when and where the survey appears',
        Component: SurveyDisplayConditionsWidget,
    },
    results: {
        label: 'Results',
        description: 'Show survey responses and question results',
        Component: SurveyResultsWidget,
    },
} satisfies PostHogWidgetViews<SurveyNotebookWidgetAttributes>
