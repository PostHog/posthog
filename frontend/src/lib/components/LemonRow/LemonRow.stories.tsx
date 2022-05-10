import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { IconInfo, IconPremium } from '../icons'
import { LemonRow, LemonRowProps } from './LemonRow'

export default {
    title: 'Lemon UI/Lemon Row',
    component: LemonRow,
    argTypes: {
        icon: {
            defaultValue: <IconPremium />,
        },
        children: {
            defaultValue: 'Information',
        },
    },
} as ComponentMeta<typeof LemonRow>

const Template: ComponentStory<typeof LemonRow> = (props: LemonRowProps<keyof JSX.IntrinsicElements>) => {
    return <LemonRow {...props} />
}

export const Default = Template.bind({})
Default.args = {}

export const TextOnly = Template.bind({})
TextOnly.args = {
    icon: null,
}

export const IconOnly = Template.bind({})
IconOnly.args = {
    children: null,
}

export const Outlined = Template.bind({})
Outlined.args = {
    outlined: true,
}

export const Success = Template.bind({})
Success.args = {
    status: 'success',
}

export const Warning = Template.bind({})
Warning.args = {
    status: 'warning',
}

export const Danger = Template.bind({})
Danger.args = {
    status: 'danger',
}

export const Disabled = Template.bind({})
Disabled.args = {
    disabled: true,
}

export const Loading = Template.bind({})
Loading.args = {
    loading: true,
}

export const Small = Template.bind({})
Small.args = {
    size: 'small',
}

export const Large = Template.bind({})
Large.args = {
    size: 'large',
}

export const FullWidth = Template.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const WithSideIcon = Template.bind({})
WithSideIcon.args = {
    sideIcon: <IconInfo />,
}

export const WithTooltip = Template.bind({})
WithTooltip.args = {
    tooltip:
        'The lifespan of kangaroos averages at six years in the wild to in excess of 20 years in captivity, varying by the species.',
}

export const WithExtendedContent = Template.bind({})
WithExtendedContent.args = {
    type: 'stealth',
    extendedContent: "This is some extra info about this particular item. Hopefully it's helpful.",
}
