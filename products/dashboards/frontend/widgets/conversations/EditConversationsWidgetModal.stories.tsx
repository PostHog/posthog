import type { Meta, StoryObj } from '@storybook/react'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import { EditConversationsWidgetModal } from './EditConversationsWidgetModal'

const CATALOG = getDashboardWidgetCatalogEntry('conversations_recent_tickets')!
const meta: Meta<typeof EditConversationsWidgetModal> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Support/Recent tickets/Widget settings',
    component: EditConversationsWidgetModal,
    parameters: { layout: 'fullscreen', ...widgetStorybookParameters },
    args: {
        isOpen: true,
        onClose: () => undefined,
        onSave: () => Promise.resolve(),
        config: CATALOG.defaultConfig,
        name: 'Recent tickets',
        defaultTitle: 'Recent tickets',
        description: CATALOG.description,
    },
}
export default meta
type Story = StoryObj<typeof EditConversationsWidgetModal>
export const Default: Story = {}
