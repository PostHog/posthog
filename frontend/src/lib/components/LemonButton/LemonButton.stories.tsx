import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithPopup,
    LemonButtonWithPopupProps,
    LemonButtonWithSideAction,
    LemonButtonWithSideActionProps,
} from './LemonButton'
import { IconCalculate, IconInfo, IconPlus } from '../icons'
import { More, MoreProps } from './More'
import { LemonDivider } from '../LemonDivider'

export default {
    title: 'Lemon UI/Lemon Button',
    component: LemonButton,
    argTypes: {
        icon: {
            defaultValue: <IconCalculate />,
        },
        children: {
            defaultValue: 'Click me',
        },
    },
} as ComponentMeta<typeof LemonButton>

const BasicTemplate: ComponentStory<typeof LemonButton> = (props: LemonButtonProps) => {
    return <LemonButton {...props} />
}

const PopupTemplate: ComponentStory<typeof LemonButtonWithPopup> = (props: LemonButtonWithPopupProps) => {
    return <LemonButtonWithPopup {...props} />
}

const SideActionTemplate: ComponentStory<typeof LemonButtonWithSideAction> = (
    props: LemonButtonWithSideActionProps
) => {
    return <LemonButtonWithSideAction {...props} />
}

const MoreTemplate: ComponentStory<typeof More> = (props: MoreProps) => {
    return <More {...props} />
}

export const Default = BasicTemplate.bind({})
Default.args = {}

export const TextOnly = BasicTemplate.bind({})
TextOnly.args = {
    icon: null,
}

export const IconOnly = BasicTemplate.bind({})
IconOnly.args = {
    children: null,
}

export const Primary = BasicTemplate.bind({})
Primary.args = {
    type: 'primary',
}

export const Secondary = BasicTemplate.bind({})
Secondary.args = {
    type: 'secondary',
}

export const Tertiary = BasicTemplate.bind({})
Tertiary.args = {
    type: 'tertiary',
}

export const Stealth = BasicTemplate.bind({})
Stealth.args = {
    type: 'stealth',
}

export const Highlighted = BasicTemplate.bind({})
Highlighted.args = {
    type: 'highlighted',
}

export const Alt = BasicTemplate.bind({})
Alt.args = {
    type: 'alt',
}

export const WithInternalLink = BasicTemplate.bind({})
WithInternalLink.args = {
    to: '/home',
}

export const WithExternalLink = BasicTemplate.bind({})
WithExternalLink.args = {
    href: 'https://example.com/',
}

export const Success = BasicTemplate.bind({})
Success.args = {
    status: 'success',
}

export const Warning = BasicTemplate.bind({})
Warning.args = {
    status: 'warning',
}

export const Danger = BasicTemplate.bind({})
Danger.args = {
    status: 'danger',
}

export const Disabled = BasicTemplate.bind({})
Disabled.args = {
    disabled: true,
}

export const Loading = BasicTemplate.bind({})
Loading.args = {
    loading: true,
}

export const Small = BasicTemplate.bind({})
Small.args = {
    size: 'small',
}

export const Large = BasicTemplate.bind({})
Large.args = {
    size: 'large',
}

export const FullWidth = BasicTemplate.bind({})
FullWidth.args = {
    fullWidth: true,
}

export const WithSideIcon = BasicTemplate.bind({})
WithSideIcon.args = {
    sideIcon: <IconInfo />,
}

export const WithSideAction = SideActionTemplate.bind({}) // FIXME: This one's too wide
WithSideAction.args = {
    sideAction: {
        icon: <IconPlus />,
        tooltip: 'Create new',
    },
}

export const FullWidthWithSideAction = SideActionTemplate.bind({})
FullWidthWithSideAction.args = {
    fullWidth: true,
    sideAction: {
        icon: <IconPlus />,
        tooltip: 'Create new',
    },
}

export const WithPopupToTheRight = PopupTemplate.bind({})
WithPopupToTheRight.args = {
    popup: {
        overlay: (
            <>
                <LemonButton type="stealth" fullWidth>
                    Kakapo
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Kangaroo
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Kingfisher
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Koala
                </LemonButton>
            </>
        ),
        placement: 'right-start',
    },
}

export const WithPopupToTheBottom = PopupTemplate.bind({})
WithPopupToTheBottom.args = {
    popup: {
        overlay: (
            <>
                <LemonButton type="stealth" fullWidth>
                    Kakapo
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Kangaroo
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Kingfisher
                </LemonButton>
                <LemonButton type="stealth" fullWidth>
                    Koala
                </LemonButton>
            </>
        ),
        placement: 'bottom',
        sameWidth: true,
    },
}

export const WithTooltip = BasicTemplate.bind({})
WithTooltip.args = {
    tooltip: 'The flux capacitor will be reloaded. This might take up to 14 hours.',
}

export const WithExtendedContent = BasicTemplate.bind({})
WithExtendedContent.args = {
    type: 'stealth',
    extendedContent: "This is some extra info about this particular item. Hopefully it's helpful.",
}

export const More_ = MoreTemplate.bind({})
More_.args = {
    overlay: (
        <>
            <LemonButton type="stealth" fullWidth>
                View
            </LemonButton>
            <LemonButton type="stealth" fullWidth>
                Edit
            </LemonButton>
            <LemonDivider />
            <LemonButton type="stealth" status="danger" fullWidth>
                Delete
            </LemonButton>
        </>
    ),
}
