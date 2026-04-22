import type { Meta, StoryObj } from '@storybook/react'

import { DashboardPlacement, DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

import { ButtonTileCard } from './ButtonTileCard'

const meta: Meta = {
    title: 'Components/Cards/Button Tile Card',
    component: ButtonTileCard,
    parameters: {},
}
export default meta
type Story = StoryObj<{}>

const makeButtonTile = (
    url: string,
    text: string,
    opts: {
        placement?: 'left' | 'right'
        style?: 'primary' | 'secondary'
        transparentBackground?: boolean
        color?: InsightColor | null
    } = {}
): DashboardTile<QueryBasedInsightModel> => {
    return {
        id: 1,
        button_tile: {
            url,
            text,
            placement: opts.placement ?? 'left',
            style: opts.style ?? 'primary',
        },
        transparent_background: opts.transparentBackground ?? false,
        layouts: {},
        color: opts.color ?? null,
    }
}

export const Template: Story = {
    render: () => {
        return (
            <div className="flex flex-wrap gap-4">
                <div className="relative w-fit">
                    <h5>Primary button (left)</h5>
                    <ButtonTileCard
                        buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="relative w-fit">
                    <h5>Secondary button (left)</h5>
                    <ButtonTileCard
                        buttonTile={makeButtonTile('https://posthog.com', 'Learn more', { style: 'secondary' })}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="relative w-fit">
                    <h5>Primary button (right)</h5>
                    <ButtonTileCard
                        buttonTile={makeButtonTile('https://posthog.com', 'Get started', { placement: 'right' })}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="relative w-fit">
                    <h5>With resize handles</h5>
                    <ButtonTileCard
                        showResizeHandles={true}
                        buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog')}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
            </div>
        )
    },
}

export const TransparentBackground: Story = {
    render: () => {
        return (
            <div className="flex flex-wrap gap-4 bg-surface-secondary p-4">
                <div className="relative w-fit">
                    <h5>Transparent background (view mode)</h5>
                    <ButtonTileCard
                        buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog', {
                            transparentBackground: true,
                        })}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
                <div className="relative w-fit">
                    <h5>Transparent background (edit mode — dashed border)</h5>
                    <ButtonTileCard
                        showResizeHandles={true}
                        buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog', {
                            transparentBackground: true,
                        })}
                        placement={DashboardPlacement.Dashboard}
                    />
                </div>
            </div>
        )
    },
}

export const WithMoreButton: Story = {
    render: () => {
        return (
            <div className="relative w-fit">
                <ButtonTileCard
                    buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog')}
                    moreButtonOverlay={<div>more button</div>}
                    placement={DashboardPlacement.Dashboard}
                />
            </div>
        )
    },
}

export const WithMoreButtonPlacedInPublic: Story = {
    render: () => {
        return (
            <div className="relative w-fit">
                <ButtonTileCard
                    buttonTile={makeButtonTile('https://posthog.com', 'Visit PostHog (more button hidden)')}
                    moreButtonOverlay={<div>more button</div>}
                    placement={DashboardPlacement.Public}
                />
            </div>
        )
    },
}
