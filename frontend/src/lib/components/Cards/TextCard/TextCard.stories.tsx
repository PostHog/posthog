import type { Meta, StoryObj } from '@storybook/react'

import { AccessControlLevel, DashboardPlacement, DashboardTile, DashboardType, InsightColor } from '~/types'

import { DashboardTextItem } from 'products/dashboards/frontend/components/DashboardTextItem/DashboardTextItem'

import { TextCard } from './TextCard'
import { TextCardModal } from './TextCardModal'
import { WORD_ART_PRESETS } from './WordArt/wordArtPresets'

const meta: Meta = {
    title: 'Components/Cards/Text Card',
    component: TextCard,
    parameters: {},
}
export default meta
type Story = StoryObj<{}>

const makeTextTile = (body: string, color: InsightColor | null = null, agentContext?: string): DashboardTile => {
    return {
        id: 1,
        text: {
            body: body,
            agent_context: agentContext,
            last_modified_by: {
                id: 1,
                uuid: 'a uuid',
                distinct_id: 'another uuid',
                first_name: 'paul',
                email: 'paul@posthog.com',
            },
            last_modified_at: '2022-04-01 12:24:36',
        },

        layouts: {},
        color,
    }
}

export const Template: Story = {
    render: () => {
        return (
            <div className="flex flex-wrap gap-2">
                <div>
                    <h5>basic text</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        textTile={makeTextTile('basic text')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div>
                    <h5>markdown text</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        textTile={makeTextTile('# a title \n\n **formatted** _text_')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div>
                    <h5>Long text</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        style={{ height: '250px', width: '300px' }}
                        textTile={makeTextTile(
                            '# long text which has a very long title so is too big both X and Y, what shall we do?! Oh what shall we do?\n\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n'
                        )}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div>
                    <h5>with resize handles</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        showResizeHandles={true}
                        textTile={makeTextTile('showing handles')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="w-full h-[200px]">
                    <h5>Large Card</h5>
                    <TextCard
                        className="h-full w-full react-grid-item react-draggable cssTransforms react-resizable"
                        textTile={makeTextTile('basic text')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
            </div>
        )
    },
}

export const WordArt: Story = {
    render: () => {
        const body = WORD_ART_PRESETS.map((preset) => `<span data-word-art="${preset.id}">${preset.label}</span>`).join(
            '\n\n'
        )
        return (
            <div className="max-w-160">
                <TextCard
                    textTile={makeTextTile(`# Every word art style\n\n${body}`)}
                    placement={DashboardPlacement.Dashboard}
                />
            </div>
        )
    },
}

export const WithMoreButton: Story = {
    render: () => {
        return (
            <div>
                <TextCard
                    textTile={makeTextTile('basic text')}
                    moreButtonOverlay={<div>more button</div>}
                    placement={DashboardPlacement.Dashboard}
                />
            </div>
        )
    },
}

export const WithAgentContext: Story = {
    render: () => {
        return (
            <div className="h-[240px] max-w-160">
                <DashboardTextItem
                    className="h-full"
                    tile={makeTextTile(
                        'This chart shows weekly activated organizations.',
                        null,
                        'Semantic layer metric: activation_rate. Keep the weekly date range when editing this tile.'
                    )}
                    placement={DashboardPlacement.Dashboard}
                    dashboardId={1}
                    onEdit={() => undefined}
                    onDuplicate={() => undefined}
                />
            </div>
        )
    },
}

export const EditModalWithAgentContext: Story = {
    parameters: {
        testOptions: {
            snapshotTargetSelector: '[role="dialog"]',
            waitForSelector: '[role="dialog"]',
        },
    },
    render: () => {
        const dashboard = {
            id: 1,
            name: 'Activation dashboard',
            description: '',
            pinned: false,
            created_at: '2026-01-01T00:00:00Z',
            created_by: null,
            last_accessed_at: null,
            is_shared: false,
            deleted: false,
            creation_mode: 'default',
            tiles: [
                makeTextTile(
                    'This chart shows weekly activated organizations.',
                    null,
                    'Semantic layer metric: activation_rate. Keep the weekly date range when editing this tile.'
                ),
            ],
            filters: {},
            tags: [],
            user_access_level: AccessControlLevel.Editor,
        } as DashboardType

        return (
            <div className="min-h-screen w-full">
                <TextCardModal isOpen onClose={() => undefined} dashboard={dashboard} textTileId={1} />
            </div>
        )
    },
}

export const WithMoreButtonPlacedInPublic: Story = {
    render: () => {
        return (
            <div>
                <TextCard
                    textTile={makeTextTile('basic text, more button should be hidden')}
                    moreButtonOverlay={<div>more button</div>}
                    placement={DashboardPlacement.Public}
                />
            </div>
        )
    },
}
