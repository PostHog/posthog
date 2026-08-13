import type { Meta, StoryObj } from '@storybook/react'

import { DashboardPlacement, DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

import { TextCard } from './TextCard'
import { WORD_ART_PRESETS } from './WordArt/wordArtPresets'

const meta: Meta = {
    title: 'Components/Cards/Text Card',
    component: TextCard,
    parameters: {},
}
export default meta
type Story = StoryObj<{}>

const makeTextTile = (body: string, color: InsightColor | null = null): DashboardTile<QueryBasedInsightModel> => {
    return {
        id: 1,
        text: {
            body: body,
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
            <div className="flex flex-wrap gap-2 rounded-lg border-2 border-dashed p-4 shadow-sm">
                <div>
                    <h5 className="mb-1 font-semibold uppercase tracking-wide">basic text</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        textTile={makeTextTile('basic text')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div>
                    <h5 className="mb-1 font-semibold uppercase tracking-wide">markdown text</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        textTile={makeTextTile('# a title \n\n **formatted** _text_')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div>
                    <h5 className="mb-1 font-semibold uppercase tracking-wide">Long text</h5>
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
                    <h5 className="mb-1 font-semibold uppercase tracking-wide">with resize handles</h5>
                    <TextCard
                        className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                        showResizeHandles={true}
                        textTile={makeTextTile('showing handles')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="w-full h-[200px]">
                    <h5 className="mb-1 font-semibold uppercase tracking-wide">Large Card</h5>
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
            <div className="max-w-160 rounded-lg border-2 border-dashed p-4 shadow-sm">
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
            <div className="rounded-lg bg-primary/5 p-4">
                <TextCard
                    textTile={makeTextTile('basic text')}
                    moreButtonOverlay={
                        <div className="rounded bg-primary px-2 py-1 text-xs font-semibold text-white">more button</div>
                    }
                    placement={DashboardPlacement.Dashboard}
                />
            </div>
        )
    },
}

export const WithMoreButtonPlacedInPublic: Story = {
    render: () => {
        return (
            <div className="rounded-lg bg-primary/5 p-4">
                <TextCard
                    textTile={makeTextTile('basic text, more button should be hidden')}
                    moreButtonOverlay={
                        <div className="rounded bg-primary px-2 py-1 text-xs font-semibold text-white">more button</div>
                    }
                    placement={DashboardPlacement.Public}
                />
            </div>
        )
    },
}
