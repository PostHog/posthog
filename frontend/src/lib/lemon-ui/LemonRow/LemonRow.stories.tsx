import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { IconInfo, IconPremium } from 'lib/lemon-ui/icons'
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

export const Default: Story = {
    render: Template,

    args: {
        children: 'Information',
        icon: <IconPremium />,
    },
}

export const TextOnly: Story = {
    render: Template,

    args: {
        ...Default.args,
        icon: null,
    },
}

export const IconOnly: Story = {
    render: Template,

    args: {
        ...Default.args,
        children: null,
    },
}

export const Outlined: Story = {
    render: Template,

    args: {
        ...Default.args,
        outlined: true,
    },
}

export const Success: Story = {
    render: Template,

    args: {
        ...Default.args,
        status: 'success',
    },
}

export const Warning: Story = {
    render: Template,

    args: {
        ...Default.args,
        status: 'warning',
    },
}

export const Danger: Story = {
    render: Template,

    args: {
        ...Default.args,
        status: 'danger',
    },
}

export const Disabled: Story = {
    render: Template,

    args: {
        ...Default.args,
        disabled: true,
    },
}

export const Loading: Story = {
    render: Template,

    args: {
        ...Default.args,
        loading: true,
    },
}

export const Small: Story = {
    render: Template,

    args: {
        ...Default.args,
        outlined: true,
        size: 'small',
    },
}

export const Tall: Story = {
    render: Template,

    args: {
        ...Default.args,
        outlined: true,
        size: 'tall',
    },
}

export const Large: Story = {
    render: Template,

    args: {
        ...Default.args,
        outlined: true,
        size: 'large',
    },
}

export const FullWidth: Story = {
    render: Template,

    args: {
        ...Default.args,
        outlined: true,
        fullWidth: true,
    },
}

export const WithSideIcon: Story = {
    render: Template,

    args: {
        ...Default.args,
        sideIcon: <IconInfo />,
    },
}

export const WithTooltip: Story = {
    render: Template,

    args: {
        ...Default.args,
        tooltip:
            'The lifespan of kangaroos averages at six years in the wild to in excess of 20 years in captivity, varying by the species.',
    },
}

export const WithExtendedContent: Story = {
    render: Template,

    args: {
        ...Default.args,
        type: 'stealth',
        extendedContent: "This is some extra info about this particular item. Hopefully it's helpful.",
    },
}
