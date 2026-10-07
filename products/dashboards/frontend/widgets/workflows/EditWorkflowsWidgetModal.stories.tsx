import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditWorkflowsWidgetModal } from './EditWorkflowsWidgetModal'

const CATALOG = getDashboardWidgetCatalogEntry('workflows_list')!
const DEFAULT_CONFIG = CATALOG.defaultConfig as Record<string, unknown>

function EditWorkflowsWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Workflow activity',
    defaultTitle = CATALOG.headerTitle ?? CATALOG.label,
    description = CATALOG.description,
}: Partial<DashboardWidgetEditModalProps>): JSX.Element {
    return (
        <EditWorkflowsWidgetModal
            isOpen={isOpen}
            onClose={onClose}
            config={config}
            onSave={onSave}
            name={name}
            defaultTitle={defaultTitle}
            description={description}
        />
    )
}

// Storybook CSF requires a string literal `title` derived from catalog groupLabel/label.
const meta: Meta<typeof EditWorkflowsWidgetModalStory> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Workflows/Workflow activity/Widget settings',
    component: EditWorkflowsWidgetModalStory,
    parameters: { layout: 'fullscreen', ...widgetStorybookParameters },
    args: { config: { ...DEFAULT_CONFIG, limit: 5 } },
}
export default meta
type Story = StoryObj<typeof EditWorkflowsWidgetModalStory>

export const Default: Story = {}
