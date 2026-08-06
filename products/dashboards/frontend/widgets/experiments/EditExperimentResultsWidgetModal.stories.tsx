import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { experimentsSampleListRows } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditExperimentResultsWidgetModal } from './EditExperimentResultsWidgetModal'

const EXPERIMENT_RESULTS_CATALOG = getDashboardWidgetCatalogEntry('experiment_results')!
const DEFAULT_CONFIG = EXPERIMENT_RESULTS_CATALOG.defaultConfig as Record<string, unknown>

// The settings modal embeds the searchable experiment picker (experimentPickerLogic) — mock the
// list/retrieve endpoints so the options and the selected experiment resolve.
const pickerExperiments = experimentsSampleListRows.map(({ id, name, created_by }) => ({ id, name, created_by }))
const experimentsApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/experiments/': () => [
            200,
            { results: pickerExperiments, count: pickerExperiments.length },
        ],
        '/api/projects/:team_id/experiments/:id/': ({ params }) => {
            const id = Number(params.id)
            return [200, pickerExperiments.find((experiment) => experiment.id === id) ?? pickerExperiments[0]]
        },
    },
})

type EditExperimentResultsWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditExperimentResultsWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Experiment results',
    defaultTitle = EXPERIMENT_RESULTS_CATALOG.headerTitle ?? EXPERIMENT_RESULTS_CATALOG.label,
    description = EXPERIMENT_RESULTS_CATALOG.description,
    ...props
}: EditExperimentResultsWidgetModalStoryProps): JSX.Element {
    return (
        <EditExperimentResultsWidgetModal
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
const meta: Meta<typeof EditExperimentResultsWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Experiments/Experiment results/Widget settings',
    component: EditExperimentResultsWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [experimentsApiDecorator],
    args: {
        config: { ...DEFAULT_CONFIG, experimentId: 101 },
    },
}

export default meta

type Story = StoryObj<typeof EditExperimentResultsWidgetModalStory>

export const Default: Story = {}
