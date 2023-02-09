import { Meta, Story } from '@storybook/react'
import { DashboardTile, InsightColor } from '~/types'
import { TextCard, TextCardProps } from './TextCard'

export default {
    title: 'Components/Cards/Text Card',
    component: TextCard,
    parameters: {},
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
    }
}

function CardWrapper(props: Partial<TextCardProps>): JSX.Element {
    return (
        <div className={'w-11/12 max-w-100 h-100 relative'}>
            <TextCard dashboardId={1} textTile={props.textTile || makeTextTile('unknown')} {...props} />
        </div>
    )
}

export const BasicText: Story = () => {
    return <CardWrapper textTile={makeTextTile('basic text')} />
}

export const WithResizeHandles: Story = () => {
    return <CardWrapper showResizeHandles={true} canResizeWidth={true} textTile={makeTextTile('showing handles')} />
}

export const MarkdownText: Story = () => {
    return <CardWrapper textTile={makeTextTile('# a title \n\n **formatted** _text_')} />
}

export const VeryLongText: Story = () => {
    return (
        <CardWrapper
            textTile={makeTextTile(
                '# long text which has a very long title so is too big both X and Y, what shall we do?! Oh what shall we do?\n\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n * has many lines\n'
            )}
        />
    )
}
