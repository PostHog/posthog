import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditExperimentsListWidgetModal } from './EditExperimentsListWidgetModal'

const EXPERIMENTS_LIST_CATALOG = getDashboardWidgetCatalogEntry('experiments_list')!
const DEFAULT_CONFIG = EXPERIMENTS_LIST_CATALOG.defaultConfig as Record<string, unknown>

type EditExperimentsListWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditExperimentsListWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Experiments',
    defaultTitle = EXPERIMENTS_LIST_CATALOG.headerTitle ?? EXPERIMENTS_LIST_CATALOG.label,
    description = EXPERIMENTS_LIST_CATALOG.description,
    ...props
}: EditExperimentsListWidgetModalStoryProps): JSX.Element {
    return (
        <EditExperimentsListWidgetModal
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
const meta: Meta<typeof EditExperimentsListWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Experiments/Experiments/Widget settings',
    component: EditExperimentsListWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [],
    args: {
        config: { ...DEFAULT_CONFIG, status: 'running', orderBy: 'created_at', orderDirection: 'DESC' },
    },
}

export default meta

type Story = StoryObj<typeof EditExperimentsListWidgetModalStory>

export const Default: Story = {}
