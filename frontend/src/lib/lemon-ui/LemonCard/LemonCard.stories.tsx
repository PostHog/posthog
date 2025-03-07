import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonCard, LemonCardProps } from './LemonCard'

type Story = StoryObj<typeof LemonCard>
const meta: Meta<typeof LemonCard> = {
    title: 'Lemon UI/Lemon Card',
    component: LemonCard,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonCard> = (props: LemonCardProps) => {
    // We need to explicitly set size on the banner's parent, because LemonBanner is a CSS container
    // See: https://stackoverflow.com/a/73980194/3515268
    return (
        <div>
            <LemonCard {...props}>
                <span>Tis a lemon card</span>
            </LemonCard>
        </div>
    )
}

export const Default: Story = Template.bind({})
Default.args = {}

export const Focused: Story = Template.bind({})
Focused.args = { focused: true }

export const HoverEffect: Story = Template.bind({})
HoverEffect.args = { hoverEffect: true }

export const Closeable: Story = Template.bind({})
Closeable.args = { closeable: true }
