import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditSurveyResultsWidgetModal } from './EditSurveyResultsWidgetModal'

const SURVEY_RESULTS_CATALOG = getDashboardWidgetCatalogEntry('survey_results')!
const DEFAULT_CONFIG = SURVEY_RESULTS_CATALOG.defaultConfig as Record<string, unknown>

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

const meta: Meta<typeof EditSurveyResultsWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Surveys/Survey results/Widget settings',
    component: EditSurveyResultsWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    args: {
        config: { ...DEFAULT_CONFIG, surveyId: 'survey-101' },
    },
}

export default meta

type Story = StoryObj<typeof EditSurveyResultsWidgetModalStory>

export const Default: Story = {}
