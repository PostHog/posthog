import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { IconInfo } from '@posthog/icons'

import { IconPremium } from 'lib/lemon-ui/icons'

import { LemonRow, LemonRowProps } from './LemonRow'

type Story = StoryObj<typeof LemonRow>
const meta: Meta<typeof LemonRow> = {
    title: 'Lemon UI/Lemon Row',
    component: LemonRow,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonRow> = (props: LemonRowProps<keyof JSX.IntrinsicElements>) => {
    return <LemonRow {...props} />
}

export const Default: Story = Template.bind({})
Default.args = {
    children: 'Information',
    icon: <IconPremium />,
}

export const TextOnly: Story = Template.bind({})
TextOnly.args = {
    ...Default.args,
    icon: null,
}

export const IconOnly: Story = Template.bind({})
IconOnly.args = {
    ...Default.args,
    children: null,
}

export const Outlined: Story = Template.bind({})
Outlined.args = {
    ...Default.args,
    outlined: true,
}

export const Success: Story = Template.bind({})
Success.args = {
    ...Default.args,
    status: 'success',
}

export const Warning: Story = Template.bind({})
Warning.args = {
    ...Default.args,
    status: 'warning',
}

export const Danger: Story = Template.bind({})
Danger.args = {
    ...Default.args,
    status: 'danger',
}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    ...Default.args,
    disabled: true,
}

export const Loading: Story = Template.bind({})
Loading.args = {
    ...Default.args,
    loading: true,
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
}

export const Small: Story = Template.bind({})
Small.args = {
    ...Default.args,
    outlined: true,
    size: 'small',
}

export const Tall: Story = Template.bind({})
Tall.args = {
    ...Default.args,
    outlined: true,
    size: 'tall',
}

export const Large: Story = Template.bind({})
Large.args = {
    ...Default.args,
    outlined: true,
    size: 'large',
}

export const FullWidth: Story = Template.bind({})
FullWidth.args = {
    ...Default.args,
    outlined: true,
    fullWidth: true,
}

export const WithSideIcon: Story = Template.bind({})
WithSideIcon.args = {
    ...Default.args,
    sideIcon: <IconInfo />,
}

export const WithTooltip: Story = Template.bind({})
WithTooltip.args = {
    ...Default.args,
    tooltip:
        'The lifespan of kangaroos averages at six years in the wild to in excess of 20 years in captivity, varying by the species.',
}

export const WithExtendedContent: Story = Template.bind({})
WithExtendedContent.args = {
    ...Default.args,
    type: 'stealth',
    extendedContent: "This is some extra info about this particular item. Hopefully it's helpful.",
}
