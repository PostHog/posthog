import { Meta, Story } from '@storybook/react'

import { DashboardTile, InsightColor, QueryBasedInsightModel } from '~/types'

import { TextCard } from './TextCard'

const meta: Meta = {
    title: 'Components/Cards/Text Card',
    component: TextCard,
    parameters: {},
}
export default meta
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

export const Template: Story = () => {
    return (
        <div className="flex flex-wrap gap-2">
            <div>
                <h5>basic text</h5>
                <TextCard
                    className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                    dashboardId={1}
                    textTile={makeTextTile('basic text')}
                />
            </div>
            <div>
                <h5>markdown text</h5>
                <TextCard
                    className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                    dashboardId={1}
                    textTile={makeTextTile('# a title \n\n **formatted** _text_')}
                />
            </div>
            <div>
                <h5>Long text</h5>
                <TextCard
                    className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                    style={{ height: '250px', width: '300px' }}
                    dashboardId={1}
                    textTile={makeTextTile(
                        '# long text which has a very long title so is too big both X and Y, what shall we do?! Oh what shall we do?\n\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n'
                    )}
                />
            </div>
            <div>
                <h5>with resize handles</h5>
                <TextCard
                    className="react-grid-item react-draggable cssTransforms react-resizable min-h-60 min-w-[15rem]"
                    dashboardId={1}
                    showResizeHandles={true}
                    canResizeWidth={true}
                    textTile={makeTextTile('showing handles')}
                />
            </div>
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div className="w-full" style={{ height: '200px' }}>
                <h5>Large Card</h5>
                <TextCard
                    className="h-full w-full react-grid-item react-draggable cssTransforms react-resizable"
                    dashboardId={1}
                    textTile={makeTextTile('basic text')}
                />
            </div>
        </div>
    )
}
