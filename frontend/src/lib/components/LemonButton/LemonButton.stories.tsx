import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithPopup,
    LemonButtonWithPopupProps,
    LemonButtonWithSideAction,
} from './LemonButton'
import { IconCalculate, IconInfo, IconPlus } from '../icons'
import { More, MoreProps } from './More'
import { LemonDivider } from '../LemonDivider'
import { capitalizeFirstLetter } from 'lib/utils'

const statuses: LemonButtonProps['status'][] = [undefined, 'danger', 'highlighted', 'muted', 'success', 'warning']
const types: LemonButtonProps['type'][] = ['default', 'primary', 'secondary', 'tertiary', 'stealth', 'alt']

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

export const Default = BasicTemplate.bind({})
Default.args = {}

const StatusesTemplate: ComponentStory<typeof LemonButton> = ({ ...props }) => {
    return (
        <div className="flex gap-2 border rounded-lg p-2">
            {statuses.map((status, j) => (
                <LemonButton key={j} status={status} icon={<IconCalculate />} {...props}>
                    {!(props as any).noText ? capitalizeFirstLetter(status || 'default') : undefined}
                </LemonButton>
            ))}
        </div>
    )
}

const TypesAndStatusesTemplate: ComponentStory<typeof LemonButton> = (props) => {
    return (
        <div className="space-y-2">
            {types.map((type) => (
                <>
                    <h5>type={capitalizeFirstLetter(type || '')}</h5>
                    <StatusesTemplate {...props} type={type} />
                </>
            ))}
        </div>
    )
}

export const TypesAndStatuses = TypesAndStatusesTemplate.bind({})
TypesAndStatuses.args = {}

const PopupTemplate: ComponentStory<typeof LemonButtonWithPopup> = (props: LemonButtonWithPopupProps) => {
    return <LemonButtonWithPopup {...props} />
}

const MoreTemplate: ComponentStory<typeof More> = (props: MoreProps) => {
    return <More {...props} />
}

export const IconOnly = StatusesTemplate.bind({})
IconOnly.args = { noText: true } as any

export const Sizes = (): JSX.Element => {
    const sizes: LemonButtonProps['size'][] = ['small', 'medium', 'large', 'tall']

    return (
        <div className="space-y-2">
            {sizes.map((size) => (
                <>
                    <h5>size={size}</h5>
                    <StatusesTemplate size={size} type="primary" />
                </>
            ))}
        </div>
    )
}

export const Disabled = StatusesTemplate.bind({})
Disabled.args = { disabled: true }

export const Loading = StatusesTemplate.bind({})
Loading.args = { loading: true }

export const WithSideIcon = StatusesTemplate.bind({})
WithSideIcon.args = { sideIcon: <IconInfo /> }

export const FullWidth = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <LemonButton fullWidth>Full Width</LemonButton>
            <LemonButton type="primary" fullWidth>
                Full Width
            </LemonButton>
            <LemonButton type="secondary" fullWidth icon={<IconCalculate />}>
                Full Width
            </LemonButton>
        </div>
    )
}

export const WithSideAction = (): JSX.Element => {
    return (
        <div className="flex items-center gap-2">
            {statuses.map((status, i) => (
                <LemonButtonWithSideAction
                    key={i}
                    sideAction={{
                        icon: <IconPlus />,
                        tooltip: 'Create new',
                        onClick: () => alert('Side action!'),
                    }}
                    status={status}
                >
                    {capitalizeFirstLetter(status || 'Default')}
                </LemonButtonWithSideAction>
            ))}
        </div>
    )
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
