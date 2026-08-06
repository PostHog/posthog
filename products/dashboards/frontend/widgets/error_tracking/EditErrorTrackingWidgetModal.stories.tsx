import type { Meta, StoryObj } from '@storybook/react'

import {
    widgetStorybookParameters,
    withErrorTrackingProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditErrorTrackingWidgetModal } from './EditErrorTrackingWidgetModal'

const ERROR_TRACKING_CATALOG = getDashboardWidgetCatalogEntry('error_tracking_list')!
const DEFAULT_CONFIG = ERROR_TRACKING_CATALOG.defaultConfig as Record<string, unknown>

type EditErrorTrackingWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditErrorTrackingWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Top issues',
    defaultTitle = ERROR_TRACKING_CATALOG.headerTitle ?? ERROR_TRACKING_CATALOG.label,
    description = 'Track the most common errors affecting your users.',
    ...props
}: EditErrorTrackingWidgetModalStoryProps): JSX.Element {
    return (
        <EditErrorTrackingWidgetModal
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
const meta: Meta<typeof EditErrorTrackingWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Error tracking/Top issues/Widget settings',
    component: EditErrorTrackingWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [],
    args: {
        config: { ...DEFAULT_CONFIG, orderBy: 'occurrences', filterTestAccounts: true },
    },
}

export default meta

type Story = StoryObj<typeof EditErrorTrackingWidgetModalStory>

export const Default: Story = {
    decorators: [withErrorTrackingProjectState(true)],
}

export const BeforeExceptionIngestion: Story = {
    decorators: [withErrorTrackingProjectState(false)],
}
