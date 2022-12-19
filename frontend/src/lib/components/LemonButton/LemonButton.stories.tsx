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
import { capitalizeFirstLetter, delay, range } from 'lib/utils'
import { urls } from 'scenes/urls'
import { Link } from '@posthog/lemon-ui'
import { AlertMessage } from '../AlertMessage'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'

const statuses: LemonButtonProps['status'][] = ['primary', 'danger', 'primary-alt', 'muted']
const types: LemonButtonProps['type'][] = ['primary', 'secondary', 'tertiary']

export default {
    title: 'Lemon UI/Lemon Button',
    component: LemonButton,
    parameters: { chromatic: { disableSnapshot: false } },
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

const StatusesTemplate = ({ ...props }: LemonButtonProps & { noText?: boolean }): JSX.Element => {
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

export const NoPadding = (): JSX.Element => {
    return <StatusesTemplate noText noPadding />
}

export const TextOnly = (): JSX.Element => {
    return <StatusesTemplate type={'secondary'} icon={null} />
}

export const Sizes = (): JSX.Element => {
    const sizes: LemonButtonProps['size'][] = ['small', 'medium', 'large']

    return (
        <div className="space-y-2">
            {sizes.map((size) => (
                <>
                    <h5>size={size}</h5>
                    <StatusesTemplate size={size} type="secondary" />
                </>
            ))}
        </div>
    )
}

export const SizesIconOnly = (): JSX.Element => {
    const sizes: LemonButtonProps['size'][] = ['small', 'medium', 'large']

    return (
        <div className="space-y-2">
            {sizes.map((size) => (
                <>
                    <h5>size={size}</h5>
                    <StatusesTemplate size={size} type="secondary" noText />
                </>
            ))}
        </div>
    )
}

export const Disabled = (): JSX.Element => {
    return <StatusesTemplate disabled />
}

export const Loading = (): JSX.Element => {
    return <TypesAndStatusesTemplate loading />
}

export const LoadingViaOnClick = (): JSX.Element => {
    const { loading, onEvent } = useAsyncHandler(async () => await delay(1000))

    return (
        <div className="space-y-2">
            <p>
                For simple use-cases, you may want to use a button click to trigger something async and show a loading
                state. Generally speaking this should exist in a <code>kea logic</code> but for simple cases you can use
                the <code>useAsyncHandler</code>
            </p>
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" loading={loading} onClick={onEvent}>
                    I load for one second
                </LemonButton>
            </div>
        </div>
    )
}

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

export const MenuButtons = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <p>When a button is used inside a menu item it should have the special status **stealth**</p>
            <div className="border rounded-lg flex flex-col p-2 space-y-1">
                <LemonButton active status="stealth">
                    Active item
                </LemonButton>
                <LemonButton status="stealth">Item 1</LemonButton>
                <LemonButton status="stealth">Item 2</LemonButton>
            </div>
        </div>
    )
}

export const WithSideIcon = (): JSX.Element => {
    return <StatusesTemplate sideIcon={<IconInfo />} />
}

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
        <div className="space-y-2">
            <AlertMessage type="info">
                <b>Reminder</b> - if you just want a link, use the{' '}
                <Link to={'/?path=/docs/lemon-ui-link'} disableClientSideRouting>
                    Link component
                </Link>
            </AlertMessage>

            <p>
                Buttons can act as links via the <b>to</b> prop. If this is an internal endpoint it will be routed
                client-side
            </p>
            <LemonButton to={urls.projectHomepage()}>Internal link with "to"</LemonButton>

            <p>External links will be automatically detected and routed to normally</p>
            <LemonButton to="https://posthog.com">External link</LemonButton>

            <p>
                The <code>targetBlank</code> prop will open the link in a new window/tab, setting the appropriate
                attributed like <code>rel="noopener"</code>
            </p>
            <LemonButton to="https://posthog.com" targetBlank>
                External link with "targetBlank"
            </LemonButton>
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

export const WithVeryLongPopupToTheBottom = PopupTemplate.bind({})
WithVeryLongPopupToTheBottom.args = {
    popup: {
        overlay: (
            <>
                {range(200).map((n) => (
                    <LemonButton key={n} status="stealth" fullWidth>
                        {n.toString()}
                    </LemonButton>
                ))}
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
