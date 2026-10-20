import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { widgetStorybookParameters } from '../../components/WidgetCard/widgetCardStoryFixtures'
import { canvasAppWidgetConfigSchema } from '../../generated/widget-configs.zod'
import type { DashboardWidgetEditModalProps } from '../registry'
import { EditCanvasAppWidgetModal } from './EditCanvasAppWidgetModal'

const DEFAULT_CONFIG = canvasAppWidgetConfigSchema.parse({}) as Record<string, unknown>
const CANVAS_ID = '11111111-1111-1111-1111-111111111111'

const sampleCanvas = {
    id: CANVAS_ID,
    name: 'Support console',
    kind: 'freeform',
    description: '',
    channel: 'space-1',
    template_id: 'freeform',
    generation_task_id: null,
    pinned: false,
    pinned_at: null,
    current_version_id: 'version-1',
    published_build_id: 'build-1',
    component_meta: null,
    created_by: { id: 1, uuid: 'u', distinct_id: 'd', first_name: 'Ada', last_name: '', email: 'ada@example.com' },
    created_at: '2026-05-20T10:00:00Z',
    updated_at: '2026-05-20T10:00:00Z',
    url: `/canvases/${CANVAS_ID}`,
}

// The settings modal embeds the canvas picker (canvasPickerLogic) — mock the list/retrieve endpoints so the
// options and the selected canvas resolve.
const canvasesApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/canvases/': () => [200, { results: [sampleCanvas], count: 1 }],
        '/api/projects/:team_id/canvases/:id/': () => [200, sampleCanvas],
    },
})

type EditCanvasAppWidgetModalStoryProps = Partial<DashboardWidgetEditModalProps>

function EditCanvasAppWidgetModalStory({
    isOpen = true,
    onClose = () => undefined,
    onSave = () => Promise.resolve(),
    config = DEFAULT_CONFIG,
    name = 'Canvas app',
    defaultTitle = 'Canvas app',
    description = "A published canvas app, rendered with each viewer's own permissions.",
    ...props
}: EditCanvasAppWidgetModalStoryProps): JSX.Element {
    return (
        <EditCanvasAppWidgetModal
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
const meta: Meta<typeof EditCanvasAppWidgetModalStory> = {
    title: 'Products/Dashboards/Dashboard Widgets/Widget types/Canvas/Canvas app/Widget settings',
    component: EditCanvasAppWidgetModalStory,
    parameters: {
        layout: 'fullscreen',
        ...widgetStorybookParameters,
    },
    decorators: [canvasesApiDecorator],
    args: {
        config: { ...DEFAULT_CONFIG, canvasId: CANVAS_ID },
    },
}

export default meta

type Story = StoryObj<typeof EditCanvasAppWidgetModalStory>

export const Default: Story = {}

export const NoCanvasSelected: Story = {
    args: {
        config: DEFAULT_CONFIG,
    },
}
