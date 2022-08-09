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
import { urls } from 'scenes/urls'

const statuses: LemonButtonProps['status'][] = [
    'primary',
    'danger',
    'success',
    'warning',
    'primary-alt',
    'muted-alt',
    'stealth',
]
const types: LemonButtonProps['type'][] = ['primary', 'secondary', 'tertiary']

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
        <div className="flex gap-2 border rounded-lg p-2 flex-wrap">
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

export const NoPadding = StatusesTemplate.bind({})
NoPadding.args = { noText: true, noPadding: true } as any

export const TextOnly = StatusesTemplate.bind({})
TextOnly.args = { icon: undefined, type: 'secondary' } as any

export const Sizes = (): JSX.Element => {
    const sizes: LemonButtonProps['size'][] = ['small', 'medium', 'large']

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

export const Active = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <p>
                Sometimes you may need to keep the LemonButton in it's active state e.g. the hover state. This can be
                done by setting the <code>active</code> property
            </p>
            <div className="flex items-center gap-2">
                <LemonButton>I am not active</LemonButton>
                <LemonButton active>I am active</LemonButton>
            </div>
        </div>
    )
}

export const WithSideIcon = StatusesTemplate.bind({})
WithSideIcon.args = { sideIcon: <IconInfo /> }

export const FullWidth = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <LemonButton fullWidth>Full Width</LemonButton>
            <LemonButton type="primary" fullWidth>
                Full Width
            </LemonButton>

            <LemonButton type="primary" fullWidth center icon={<IconPlus />}>
                Full Width centered with icon
            </LemonButton>

            <LemonButtonWithSideAction
                type="secondary"
                fullWidth
                icon={<IconCalculate />}
                sideAction={{
                    icon: <IconPlus />,
                    tooltip: 'Create new',
                    onClick: () => alert('Side action!'),
                }}
            >
                Full Width with side action
            </LemonButtonWithSideAction>
        </div>
    )
}

export const WithSideAction = (): JSX.Element => {
    return (
        <div className="space-y-2">
            {types.map((type) => (
                <>
                    <h5>type={capitalizeFirstLetter(type || '')}</h5>
                    <div className="flex items-center gap-2">
                        {statuses.map((status, i) => (
                            <LemonButtonWithSideAction
                                key={i}
                                type={type}
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
                </>
            ))}
        </div>
    )
}

export const AsLinks = (): JSX.Element => {
    return (
        <div className="space-x-2">
            <LemonButton href="https://posthog.com">External link with "href"</LemonButton>

            <LemonButton to={urls.projectHomepage()}>Internal link with "to"</LemonButton>
        </div>
    )
}

export const WithPopupToTheRight = PopupTemplate.bind({})
WithPopupToTheRight.args = {
    popup: {
        overlay: (
            <>
                <LemonButton status="stealth" fullWidth>
                    Kakapo
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
                    Kangaroo
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
                    Kingfisher
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
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
                <LemonButton status="stealth" fullWidth>
                    Kakapo
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
                    Kangaroo
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
                    Kingfisher
                </LemonButton>
                <LemonButton status="stealth" fullWidth>
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

export const More_ = MoreTemplate.bind({})
More_.args = {
    overlay: (
        <>
            <LemonButton status="stealth" fullWidth>
                View
            </LemonButton>
            <LemonButton status="stealth" fullWidth>
                Edit
            </LemonButton>
            <LemonDivider />
            <LemonButton status="danger" fullWidth>
                Delete
            </LemonButton>
        </>
    ),
}
