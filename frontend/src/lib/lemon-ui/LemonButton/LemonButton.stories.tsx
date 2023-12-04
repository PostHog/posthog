import { Link } from '@posthog/lemon-ui'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import clsx from 'clsx'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { IconCalculate, IconInfo, IconPlus } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { capitalizeFirstLetter, delay, range } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithDropdown,
    LemonButtonWithDropdownProps,
    LemonButtonWithSideAction,
} from './LemonButton'
import { More } from './More'

const statuses: LemonButtonProps['status'][] = ['primary', 'danger', 'primary-alt', 'muted', 'stealth']
const types: LemonButtonProps['type'][] = ['primary', 'secondary', 'tertiary']

type Story = StoryObj<typeof LemonButton>
const meta: Meta<typeof LemonButton> = {
    title: 'Lemon UI/Lemon Button',
    component: LemonButton,
    tags: ['autodocs'],
    argTypes: {
        icon: {
            type: 'function',
        },
    },
    parameters: {
        testOptions: { include3000: true },
    },
}
export default meta
const BasicTemplate: StoryFn<typeof LemonButton> = (props: LemonButtonProps) => {
    return <LemonButton {...props} />
}

export const Default: Story = BasicTemplate.bind({})
Default.args = {
    icon: <IconCalculate />,
    children: 'Click me',
}

const StatusesTemplate = ({
    noText,
    accommodateTooltip,
    ...props
}: LemonButtonProps & { noText?: boolean; accommodateTooltip?: boolean }): JSX.Element => {
    return (
        <div className={clsx('flex gap-2 border rounded-lg p-2 flex-wrap', accommodateTooltip && 'pt-12')}>
            {statuses.map((status, j) => (
                <LemonButton key={j} status={status} icon={<IconCalculate />} {...props}>
                    {!noText ? capitalizeFirstLetter(status || 'default') : undefined}
                </LemonButton>
            ))}
        </div>
    )
}

const TypesAndStatusesTemplate: StoryFn<typeof LemonButton> = (props) => {
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

const ButtonVariants3000 = ({
    tertiary = false,
    active = false,
}: {
    tertiary?: boolean
    active?: LemonButtonProps['active']
}): JSX.Element => {
    const variants: LemonButtonProps[] = tertiary
        ? [
              { type: 'tertiary', children: 'Primary' },
              { type: 'tertiary', status: 'danger', children: 'Danger' },
          ]
        : [
              { type: 'primary', children: 'Primary' },
              { type: 'primary', status: 'primary-alt', children: 'Primary alt' },
              { type: 'secondary', children: 'Secondary' },
              { type: 'secondary', status: 'danger', children: 'Danger' },
              { type: 'secondary', stealth: true, status: 'primary', children: 'Stealth' },
          ]
    return (
        <div className="flex gap-2 flex-wrap">
            {variants.map((props, index) => (
                <LemonButton key={index} active={active} {...props} icon={<IconCalculate />} />
            ))}
        </div>
    )
}

export const Types3000: Story = () => {
    return (
        <div className="space-y-2">
            <h5>type=3D</h5>
            <div className="border rounded">
                <div className="p-2">
                    <ButtonVariants3000 />
                </div>
                <div className="p-2">
                    <h5>Active</h5>
                    <ButtonVariants3000 active />
                </div>
                <div className="p-2 bg-bg-light rounded-b">
                    <h5>Light background</h5>
                    <div className="flex gap-2 flex-wrap">
                        <ButtonVariants3000 />
                    </div>
                </div>
            </div>
            <h5>type=TERTIARY</h5>
            <div className="border rounded">
                <div className="p-2">
                    <ButtonVariants3000 tertiary />
                </div>
                <div className="p-2 bg-bg-light rounded-b">
                    <h5>Light background</h5>
                    <div className="flex gap-2 flex-wrap">
                        <ButtonVariants3000 tertiary />
                    </div>
                </div>
            </div>
        </div>
    )
}
Types3000.args = { ...Default.args }

export const TypesAndStatuses: Story = TypesAndStatusesTemplate.bind({})
TypesAndStatuses.args = { ...Default.args }

type PopoverStory = StoryObj<typeof LemonButtonWithDropdown>
const PopoverTemplate: StoryFn<typeof LemonButtonWithDropdown> = (props: LemonButtonWithDropdownProps) => {
    return <LemonButtonWithDropdown {...props} />
}

export const NoPadding = (): JSX.Element => {
    return <StatusesTemplate noText noPadding />
}

export const TextOnly = (): JSX.Element => {
    return <StatusesTemplate type={'secondary'} icon={null} />
}

export const Sizes = (): JSX.Element => {
    const sizes: LemonButtonProps['size'][] = ['xsmall', 'small', 'medium', 'large']

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
    const sizes: LemonButtonProps['size'][] = ['xsmall', 'small', 'medium', 'large']

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

export const DisabledWithReason = (): JSX.Element => {
    return <StatusesTemplate disabledReason="You're not cool enough to click this." accommodateTooltip />
}
// TODO: Add DisabledWithReason.play for a proper snapshot showcasing the tooltip

export const Loading: Story = (): JSX.Element => {
    return <TypesAndStatusesTemplate loading />
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
    },
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

export const PseudoStates = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <div className="border rounded p-2">
                <div>
                    <h5>TYPE=3D STATE=DEFAULT</h5>
                    <ButtonVariants3000 />
                </div>
                <div id="hover">
                    <h5>TYPE=3D STATE=HOVER</h5>
                    <ButtonVariants3000 />
                </div>
                <div id="active">
                    <h5>TYPE=3D STATE=HOVER,ACTIVE</h5>
                    <ButtonVariants3000 />
                </div>
            </div>
            <div className="border rounded p-2">
                <div>
                    <h5>TYPE=TERTIARY STATE=DEFAULT</h5>
                    <ButtonVariants3000 tertiary />
                </div>
                <div id="hover">
                    <h5>TYPE=TERTIARY STATE=HOVER</h5>
                    <ButtonVariants3000 tertiary />
                </div>
                <div id="active">
                    <h5>TYPE=TERTIARY STATE=HOVER,ACTIVE</h5>
                    <ButtonVariants3000 tertiary />
                </div>
            </div>
        </div>
    )
}
PseudoStates.parameters = {
    pseudo: {
        hover: ['#hover .LemonButton', '#active .LemonButton'],
        active: ['#active .LemonButton'],
    },
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
            <LemonBanner type="info">
                <b>Reminder</b> - if you just want a link, use the{' '}
                <Link to={'/?path=/docs/lemon-ui-link'} disableClientSideRouting>
                    Link component
                </Link>
            </LemonBanner>

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

export const WithDropdownToTheRight: PopoverStory = PopoverTemplate.bind({})
WithDropdownToTheRight.args = {
    ...Default.args,
    dropdown: {
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

export const WithDropdownToTheBottom: PopoverStory = PopoverTemplate.bind({})
WithDropdownToTheBottom.args = {
    ...Default.args,
    dropdown: {
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

export const WithVeryLongPopoverToTheBottom: PopoverStory = PopoverTemplate.bind({})
WithVeryLongPopoverToTheBottom.args = {
    ...Default.args,
    dropdown: {
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

export const WithTooltip: Story = BasicTemplate.bind({})
WithTooltip.args = {
    ...Default.args,
    tooltip: 'The flux capacitor will be reloaded. This might take up to 14 hours.',
}

export const More_ = (): JSX.Element => {
    return (
        <More
            overlay={
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
            }
        />
    )
}
