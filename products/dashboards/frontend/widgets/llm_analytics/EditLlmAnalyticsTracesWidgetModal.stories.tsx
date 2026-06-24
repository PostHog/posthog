import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditLlmAnalyticsTracesWidgetModal } from './EditLlmAnalyticsTracesWidgetModal'

const LLM_ANALYTICS_TRACES_CATALOG = getDashboardWidgetCatalogEntry('llm_analytics_traces')!
const DEFAULT_CONFIG = LLM_ANALYTICS_TRACES_CATALOG.defaultConfig as Record<string, unknown>

type EditLlmAnalyticsTracesWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditLlmAnalyticsTracesWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Recent traces',
    defaultTitle = LLM_ANALYTICS_TRACES_CATALOG.headerTitle ?? LLM_ANALYTICS_TRACES_CATALOG.label,
    description = 'Recent LLM traces, as on AI observability > Traces.',
    ...props
}: EditLlmAnalyticsTracesWidgetModalStoryProps): JSX.Element {
    return (
        <EditLlmAnalyticsTracesWidgetModal
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

const meta: Meta<typeof EditLlmAnalyticsTracesWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/AI observability/Recent traces/Widget settings',
    component: EditLlmAnalyticsTracesWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [],
    args: {
        config: { ...DEFAULT_CONFIG, filterTestAccounts: true, filterSupportTraces: true },
    },
}

export default meta

type Story = StoryObj<typeof EditLlmAnalyticsTracesWidgetModalStory>

export const Default: Story = {}
