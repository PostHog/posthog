import { Meta, StoryFn } from '@storybook/react'

import { LemonButton } from '../LemonButton'
import { LemonWidget, LemonWidgetProps } from './LemonWidget'

const meta: Meta<typeof LemonWidget> = {
    title: 'Lemon UI/Lemon Widget',
    component: LemonWidget,
    tags: ['autodocs'],
}
export default meta

export const _LemonWidget: StoryFn<typeof LemonWidget> = (props: LemonWidgetProps) => {
    return (
        <>
            <LemonWidget {...props} title="Widget title">
                Why does this have no padding?
            </LemonWidget>
        </>
    )
}

export const Default: StoryFn<typeof LemonWidget> = () => {
    return <LemonWidget title="Widget title">Widget content</LemonWidget>
}
export const WithActions: StoryFn<typeof LemonWidget> = () => {
    return (
        <LemonWidget
            title="Widget title"
            actions={
                <>
                    <LemonButton>Action 1</LemonButton>
                    <LemonButton>Action 2</LemonButton>
                </>
            }
        >
            Widget content
        </LemonWidget>
    )
}
export const WithOnClose: StoryFn<typeof LemonWidget> = () => {
    return (
        <LemonWidget title="Widget title" onClose={() => {}}>
            Widget content
        </LemonWidget>
    )
}
