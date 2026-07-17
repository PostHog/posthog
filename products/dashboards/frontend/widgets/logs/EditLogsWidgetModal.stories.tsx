import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditLogsWidgetModal } from './EditLogsWidgetModal'

const LOGS_CATALOG = getDashboardWidgetCatalogEntry('logs_list')!
const DEFAULT_CONFIG = LOGS_CATALOG.defaultConfig as Record<string, unknown>

type EditLogsWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditLogsWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Recent logs',
    defaultTitle = LOGS_CATALOG.headerTitle ?? LOGS_CATALOG.label,
    description = 'Keep an eye on the latest log lines from your services.',
    ...props
}: EditLogsWidgetModalStoryProps): JSX.Element {
    return (
        <EditLogsWidgetModal
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
const meta: Meta<typeof EditLogsWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Logs/Recent logs/Widget settings',
    component: EditLogsWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [],
    args: {
        config: { ...DEFAULT_CONFIG, dateRange: { date_from: '-24h' } },
    },
}

export default meta

type Story = StoryObj<typeof EditLogsWidgetModalStory>

export const Default: Story = {}
