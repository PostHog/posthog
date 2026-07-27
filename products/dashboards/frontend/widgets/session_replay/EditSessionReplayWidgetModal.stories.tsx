import type { Meta, StoryObj } from '@storybook/react'

import {
    widgetStorybookParameters,
    withSessionReplayProjectState,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditSessionReplayWidgetModal } from './EditSessionReplayWidgetModal'

const SESSION_REPLAY_CATALOG = getDashboardWidgetCatalogEntry('session_replay_list')!
const DEFAULT_CONFIG = SESSION_REPLAY_CATALOG.defaultConfig as Record<string, unknown>

type EditSessionReplayWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditSessionReplayWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Recent recordings',
    defaultTitle = SESSION_REPLAY_CATALOG.headerTitle ?? SESSION_REPLAY_CATALOG.label,
    description = 'Recent session recordings you can open in the replay player.',
    ...props
}: EditSessionReplayWidgetModalStoryProps): JSX.Element {
    return (
        <EditSessionReplayWidgetModal
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

const meta: Meta<typeof EditSessionReplayWidgetModalStory> = {
    title: 'Dashboards/Dashboard Widgets/Widget types/Session replay/Recent recordings/Widget settings',
    component: EditSessionReplayWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [],
    args: {
        config: { ...DEFAULT_CONFIG, orderBy: 'start_time', filterTestAccounts: true },
    },
}

export default meta

type Story = StoryObj<typeof EditSessionReplayWidgetModalStory>

export const Default: Story = {
    decorators: [withSessionReplayProjectState(true)],
}
