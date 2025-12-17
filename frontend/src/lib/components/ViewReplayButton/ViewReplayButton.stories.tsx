import { Meta, StoryFn } from '@storybook/react'

import { FilterLogicalOperator } from '~/types'

import { ViewReplayButton } from './ViewReplayButton'

const meta: Meta<typeof ViewReplayButton> = {
    title: 'Components/View Replay Button',
    component: ViewReplayButton,
    tags: ['autodocs'],
}

export default meta

export const Default: StoryFn<typeof ViewReplayButton> = () => {
    return (
        <ViewReplayButton
            filters={{
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    id: '$pageview',
                                    type: 'events',
                                    order: 0,
                                    name: '$pageview',
                                },
                            ],
                        },
                    ],
                },
            }}
            data-attr="example-view-recordings"
        />
    )
}

export const WithTooltip: StoryFn<typeof ViewReplayButton> = () => {
    return (
        <ViewReplayButton
            filters={{
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
            }}
            tooltip="View recordings of users who triggered this feature flag variant"
            data-attr="example-with-tooltip"
        />
    )
}

export const SecondaryButton: StoryFn<typeof ViewReplayButton> = () => {
    return (
        <ViewReplayButton
            filters={{
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
            }}
            type="secondary"
            size="small"
            data-attr="example-secondary"
        />
    )
}

export const TertiarySmall: StoryFn<typeof ViewReplayButton> = () => {
    return (
        <div className="space-y-2">
            <p>Example of tertiary buttons in a table (repeated many times):</p>
            <div className="space-y-1">
                {['Chrome', 'Firefox', 'Safari', 'Edge'].map((browser) => (
                    <div key={browser} className="flex items-center justify-between border-b p-2">
                        <span>{browser}</span>
                        <ViewReplayButton
                            filters={{
                                filter_group: {
                                    type: FilterLogicalOperator.And,
                                    values: [],
                                },
                            }}
                            type="tertiary"
                            size="xsmall"
                            tooltip={`View recordings from ${browser}`}
                            data-attr={`browser-${browser.toLowerCase()}`}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}

export const CustomLabel: StoryFn<typeof ViewReplayButton> = () => {
    return (
        <ViewReplayButton
            filters={{
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [],
                },
            }}
            label="Watch session replays"
            data-attr="example-custom-label"
        />
    )
}
