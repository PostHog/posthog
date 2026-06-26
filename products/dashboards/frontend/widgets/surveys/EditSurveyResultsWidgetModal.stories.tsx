import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditSurveyResultsWidgetModal } from './EditSurveyResultsWidgetModal'

const SURVEY_RESULTS_CATALOG = getDashboardWidgetCatalogEntry('survey_results')!
const DEFAULT_CONFIG = SURVEY_RESULTS_CATALOG.defaultConfig as Record<string, unknown>

// The settings modal embeds the searchable survey picker (surveyPickerLogic) — mock the
// list/retrieve endpoints so the options and the selected survey resolve.
const pickerSurveys = [
    { id: 'survey-101', name: 'Post-purchase feedback', archived: false, start_date: '2026-05-12T00:00:00.000Z' },
    { id: 'survey-102', name: 'NPS survey', archived: false, start_date: null },
]
const surveysApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/surveys/': () => [200, { results: pickerSurveys, count: pickerSurveys.length }],
        '/api/projects/:team_id/surveys/:id/': ({ params }) => [
            200,
            pickerSurveys.find((survey) => survey.id === params.id) ?? pickerSurveys[0],
        ],
    },
})

type EditSurveyResultsWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditSurveyResultsWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Survey results',
    defaultTitle = SURVEY_RESULTS_CATALOG.headerTitle ?? SURVEY_RESULTS_CATALOG.label,
    description = SURVEY_RESULTS_CATALOG.description,
    ...props
}: EditSurveyResultsWidgetModalStoryProps): JSX.Element {
    return (
        <EditSurveyResultsWidgetModal
            isOpen={isOpen}
            onClose={onClose}
            config={config}
            onSave={onSave}
            name={name}
            defaultTitle={defaultTitle}
            description={description}
            {...props}
        />
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof EditSurveyResultsWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Surveys/Survey results/Widget settings',
    component: EditSurveyResultsWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [surveysApiDecorator],
    args: {
        config: { ...DEFAULT_CONFIG, surveyId: 'survey-101' },
    },
}

export default meta

type Story = StoryObj<typeof EditSurveyResultsWidgetModalStory>

export const Default: Story = {}
