import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { DashboardPlacement } from '~/types'

import { WidgetCard } from '../../components/WidgetCard/WidgetCard'
import { WidgetCardBody } from '../../components/WidgetCard/WidgetCardBody'
import { WidgetCardHeader, widgetCardShouldHideMoreButton } from '../../components/WidgetCard/WidgetCardHeader'
import {
    mockMoreOverlay,
    widgetStorybookParameters,
    widgetTileFrameDecorator,
} from '../../components/WidgetCard/widgetCardStoryFixtures'
import { getDashboardWidgetCatalogEntry, getDashboardWidgetGroupLabel } from '../../widget_types/catalog'
import type { DashboardWidgetComponentProps } from '../registry'
import { CanvasAppWidget } from './CanvasAppWidget'

const CANVAS_APP_CATALOG = getDashboardWidgetCatalogEntry('canvas_app')
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
    published_build_id: null,
    component_meta: null,
    created_by: { id: 1, uuid: 'u', distinct_id: 'd', first_name: 'Ada', last_name: '', email: 'ada@example.com' },
    created_at: '2026-05-20T10:00:00Z',
    updated_at: '2026-05-20T10:00:00Z',
    url: `/canvases/${CANVAS_ID}`,
}

// The picker lists canvases and the tile opens the chosen one; both are mocked so the states render cleanly.
const canvasApiDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/canvases/': () => [200, { results: [sampleCanvas], count: 1 }],
        '/api/projects/:team_id/canvases/:id/': () => [200, sampleCanvas],
        '/api/projects/:team_id/canvases/:id/view/': () => [
            200,
            { canvas: sampleCanvas, published_build: null, current_version_id: 'version-1', has_active_build: false },
        ],
    },
})

type CanvasAppWidgetTileStoryProps = DashboardWidgetComponentProps & {
    title?: string
    description?: string
}

function CanvasAppWidgetTileStory({
    title = '',
    description = CANVAS_APP_CATALOG.description,
    ...widgetProps
}: CanvasAppWidgetTileStoryProps): JSX.Element {
    return (
        <WidgetCard className="h-full">
            <WidgetCardHeader
                layout={CANVAS_APP_CATALOG.headerLayout}
                title={title}
                defaultTitle={CANVAS_APP_CATALOG.headerTitle ?? CANVAS_APP_CATALOG.label}
                widgetTypeLabel={getDashboardWidgetGroupLabel(CANVAS_APP_CATALOG.groupId)}
                config={widgetProps.config}
                headerMeta={CANVAS_APP_CATALOG.headerMeta}
                description={description}
                showDescription
                loading={widgetProps.loading}
                shouldHideMoreButton={widgetCardShouldHideMoreButton(DashboardPlacement.Dashboard, false)}
                moreButtonOverlay={mockMoreOverlay}
            />
            <WidgetCardBody padding={false}>
                <CanvasAppWidget {...widgetProps} />
            </WidgetCardBody>
        </WidgetCard>
    )
}

const meta: Meta<typeof CanvasAppWidgetTileStory> = {
    title: 'Scenes-App/Dashboards/Widgets/CanvasApp',
    component: CanvasAppWidgetTileStory,
    decorators: [...widgetTileFrameDecorator, canvasApiDecorator],
    parameters: widgetStorybookParameters,
    args: {
        tileId: 1,
        config: CANVAS_APP_CATALOG.defaultConfig,
        loading: false,
        result: { canvas: null, needsConfiguration: true },
    },
}
export default meta

type Story = StoryObj<typeof CanvasAppWidgetTileStory>

export const NoCanvasSelected: Story = {
    args: {
        onUpdateConfig: async () => {},
    },
}

export const NoCanvasSelectedReadOnly: Story = {}

export const CanvasNotAvailable: Story = {
    args: {
        config: { canvasId: CANVAS_ID },
        result: { canvas: null, canvasNotFound: true },
    },
}

export const NothingPublishedYet: Story = {
    args: {
        config: { canvasId: CANVAS_ID },
        result: {
            canvas: {
                id: CANVAS_ID,
                name: 'Support console',
                spaceId: 'space-1',
                publishedBuildId: null,
                currentVersionId: 'version-1',
            },
        },
    },
}
