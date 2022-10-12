import { Meta, Story } from '@storybook/react'
import React from 'react'
import { DashboardTile, InsightColor } from '~/types'
import { TextCard } from './TextCard'

export default {
    title: 'Components/Cards/Text Card',
    component: TextCard,
} as Meta

const makeTextTile = (body: string, color: InsightColor | null = null): DashboardTile => {
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
        last_refresh: null,
        filters_hash: '',
        refreshing: false,
    }
}

export const Template: Story = () => {
    return (
        <div className="flex flex-wrap gap-2">
            <div>
                <h5>basic text</h5>
                <TextCard
                    className={'react-grid-item react-draggable cssTransforms react-resizable'}
                    dashboardId={1}
                    textTile={makeTextTile('basic text')}
                />
            </div>
            <div>
                <h5>markdown text</h5>
                <TextCard
                    className={'react-grid-item react-draggable cssTransforms react-resizable'}
                    dashboardId={1}
                    textTile={makeTextTile('# a title \n\n **formatted** _text_')}
                />
            </div>
            <div>
                <h5>with resize handles</h5>
                <TextCard
                    className={'react-grid-item react-draggable cssTransforms react-resizable'}
                    dashboardId={1}
                    showResizeHandles={true}
                    canResizeWidth={true}
                    textTile={makeTextTile('showing handles')}
                />
            </div>
            <div className={'w-full'} style={{ height: '200px' }}>
                <h5>Large Card</h5>
                <TextCard
                    className={'h-full w-full react-grid-item react-draggable cssTransforms react-resizable'}
                    dashboardId={1}
                    textTile={makeTextTile('basic text')}
                />
            </div>
        </div>
    )
}
