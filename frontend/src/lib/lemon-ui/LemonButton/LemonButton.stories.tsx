import { IconGear, IconInfo, IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import clsx from 'clsx'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { IconCalculate, IconLink } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { capitalizeFirstLetter, delay, range } from 'lib/utils'
import { urls } from 'scenes/urls'

import { LemonButton, LemonButtonProps, LemonButtonWithDropdown, LemonButtonWithDropdownProps } from './LemonButton'
import { More } from './More'

const statuses: LemonButtonProps['status'][] = ['default', 'alt', 'danger']
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

export const AllButtons: Story = () => {
    return (
        <div className="space-y-12">
            <div className="space-y-2">
                <h5>Primary</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary">
                        Primary Default
                    </LemonButton>
                    <LemonButton status="alt" type="primary">
                        Primary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="primary">
                        Primary Danger
                    </LemonButton>
                </div>
                <h5>Primary (loading)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary" loading>
                        Primary Default
                    </LemonButton>
                    <LemonButton status="alt" type="primary" loading>
                        Primary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="primary" loading>
                        Primary Danger
                    </LemonButton>
                </div>
                <h5>Primary (with side action)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton
                        status="default"
                        type="primary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Primary Default
                    </LemonButton>
                    <LemonButton
                        status="alt"
                        type="primary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Primary Alt
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="primary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Primary Danger
                    </LemonButton>
                </div>
                <h5>Primary (active / hover)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary" active>
                        Primary Default
                    </LemonButton>
                    <LemonButton status="alt" type="primary" active>
                        Primary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="primary" active>
                        Primary Danger
                    </LemonButton>
                </div>
                <h5>Primary (disabled)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary" disabledReason="You're not cool enough to click this.">
                        Primary Default
                    </LemonButton>
                    <LemonButton status="alt" type="primary" disabledReason="You're not cool enough to click this.">
                        Primary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="primary" disabledReason="You're not cool enough to click this.">
                        Primary Danger
                    </LemonButton>
                </div>
                <h5>Primary just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="primary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="primary" noPadding icon={<IconCalculate />} />
                </div>
                <h5>Primary (active / hover) just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="primary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="primary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="primary" active noPadding icon={<IconCalculate />} />
                </div>
            </div>
            <div className="space-y-2">
                <h5>Secondary</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="secondary">
                        Secondary Default
                    </LemonButton>
                    <LemonButton status="alt" type="secondary">
                        Secondary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="secondary">
                        Secondary Danger
                    </LemonButton>
                </div>
                <h5>Secondary (loading)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="secondary" loading>
                        Secondary Default
                    </LemonButton>
                    <LemonButton status="alt" type="secondary" loading>
                        Secondary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="secondary" loading>
                        Secondary Danger
                    </LemonButton>
                </div>
                <h5>Secondary (with side action)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton
                        status="default"
                        type="secondary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Secondary Default
                    </LemonButton>
                    <LemonButton
                        status="alt"
                        type="secondary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Secondary Alt
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Secondary Danger
                    </LemonButton>
                </div>
                <h5>Secondary active</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="secondary" active>
                        Secondary Default
                    </LemonButton>
                    <LemonButton status="alt" type="secondary" active>
                        Secondary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="secondary" active>
                        Secondary Danger
                    </LemonButton>
                </div>
                <h5>Secondary (disabled)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton
                        status="default"
                        type="secondary"
                        disabledReason="You're not cool enough to click this."
                    >
                        Secondary Default
                    </LemonButton>
                    <LemonButton status="alt" type="secondary" disabledReason="You're not cool enough to click this.">
                        Secondary Alt
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        disabledReason="You're not cool enough to click this."
                    >
                        Secondary Danger
                    </LemonButton>
                </div>
                <h5>Secondary just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="secondary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="secondary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="secondary" noPadding icon={<IconCalculate />} />
                </div>
                <h5>Secondary (active / hover) just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="secondary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="secondary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="secondary" active noPadding icon={<IconCalculate />} />
                </div>
            </div>
            <div className="space-y-2">
                <h5>Tertiary</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="tertiary">
                        Tertiary Default
                    </LemonButton>
                    <LemonButton status="alt" type="tertiary">
                        Tertiary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="tertiary">
                        Tertiary Danger
                    </LemonButton>
                </div>
                <h5>Tertiary (loading)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="tertiary" loading>
                        Tertiary Default
                    </LemonButton>
                    <LemonButton status="alt" type="tertiary" loading>
                        Tertiary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="tertiary" loading>
                        Tertiary Danger
                    </LemonButton>
                </div>
                <h5>Tertiary (with side action)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton
                        status="default"
                        type="tertiary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Tertiary Default
                    </LemonButton>
                    <LemonButton
                        status="alt"
                        type="tertiary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Tertiary Alt
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="tertiary"
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'Create new',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        Tertiary Danger
                    </LemonButton>
                </div>
                <h5>Tertiary (active / hover)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="tertiary" active>
                        Tertiary Default
                    </LemonButton>
                    <LemonButton status="alt" type="tertiary" active>
                        Tertiary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="tertiary" active>
                        Tertiary Danger
                    </LemonButton>
                </div>
                <h5>Tertiary (disabled)</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton
                        status="default"
                        type="tertiary"
                        disabledReason="You're not cool enough to click this."
                    >
                        Tertiary Default
                    </LemonButton>
                    <LemonButton status="alt" type="tertiary" disabledReason="You're not cool enough to click this.">
                        Tertiary Alt
                    </LemonButton>
                    <LemonButton status="danger" type="tertiary" disabledReason="You're not cool enough to click this.">
                        Tertiary Danger
                    </LemonButton>
                </div>
                <h5>Tertiary just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="tertiary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="tertiary" noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="tertiary" noPadding icon={<IconCalculate />} />
                </div>
                <h5>Tertiary (active / hover) just icon</h5>
                <div className="flex gap-2 p-2 rounded-lg border">
                    <LemonButton status="default" type="tertiary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="alt" type="tertiary" active noPadding icon={<IconCalculate />} />
                    <LemonButton status="danger" type="tertiary" active noPadding icon={<IconCalculate />} />
                </div>
            </div>
        </div>
    )
}

AllButtons.args = { ...Default.args }

export const TypesAndStatuses: Story = () => {
    return (
        <div className="space-y-12">
            <div className="p-2 rounded-lg border">
                <TypesAndStatusesTemplate />
            </div>
            <div className="p-2 bg-[var(--background-primary)] rounded-lg border">
                <TypesAndStatusesTemplate />
            </div>
        </div>
    )
}

TypesAndStatuses.args = { ...Default.args }

type PopoverStory = StoryObj<typeof LemonButtonWithDropdown>
const PopoverTemplate: StoryFn<typeof LemonButtonWithDropdown> = (props: LemonButtonWithDropdownProps) => {
    return <LemonButtonWithDropdown {...props} />
}

export const NoPadding = (): JSX.Element => {
    return <StatusesTemplate noText noPadding />
}

export const TextOnly = (): JSX.Element => {
    return <StatusesTemplate type="secondary" icon={null} />
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
            <div className="flex items-center gap-2">
                <LemonButton type="primary">I am not active</LemonButton>
                <LemonButton type="primary" active>
                    I am active
                </LemonButton>
            </div>
            <div className="flex items-center gap-2">
                <LemonButton type="primary" status="alt">
                    I am not active
                </LemonButton>
                <LemonButton type="primary" status="alt" active>
                    I am active
                </LemonButton>
            </div>
            <div className="flex items-center gap-2">
                <LemonButton type="secondary">I am not active</LemonButton>
                <LemonButton type="secondary" active>
                    I am active
                </LemonButton>
            </div>
            <div className="flex items-center gap-2">
                <LemonButton type="secondary" status="alt">
                    I am not active
                </LemonButton>
                <LemonButton type="secondary" status="alt" active>
                    I am active
                </LemonButton>
            </div>
        </div>
    )
}

export const PseudoStates = (): JSX.Element => {
    return (
        <div className="space-y-8">
            <div>
                <div>
                    <h5>TYPE=3D STATE=DEFAULT</h5>
                    <StatusesTemplate type="primary" />
                </div>
                <div id="hover">
                    <h5>TYPE=3D STATE=HOVER</h5>
                    <StatusesTemplate type="primary" />
                </div>
                <div id="active">
                    <h5>TYPE=3D STATE=HOVER,ACTIVE</h5>
                    <StatusesTemplate type="primary" />
                </div>
            </div>
            <div>
                <div>
                    <h5>TYPE=SECONDARY STATE=DEFAULT</h5>
                    <StatusesTemplate type="secondary" />
                </div>
                <div id="hover">
                    <h5>TYPE=SECONDARY STATE=HOVER</h5>
                    <StatusesTemplate type="secondary" />
                </div>
                <div id="active">
                    <h5>TYPE=SECONDARY STATE=HOVER,ACTIVE</h5>
                    <StatusesTemplate type="secondary" />
                </div>
            </div>
            <div>
                <div>
                    <h5>TYPE=TERTIARY STATE=DEFAULT</h5>
                    <StatusesTemplate type="tertiary" />
                </div>
                <div id="hover">
                    <h5>TYPE=TERTIARY STATE=HOVER</h5>
                    <StatusesTemplate type="tertiary" />
                </div>
                <div id="active">
                    <h5>TYPE=TERTIARY STATE=HOVER,ACTIVE</h5>
                    <StatusesTemplate type="tertiary" />
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
            <div className="border rounded-lg flex flex-col p-2 space-y-1">
                <LemonButton active>Active item</LemonButton>
                <LemonButton>Item 1</LemonButton>
                <LemonButton>Item 2</LemonButton>
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

            <LemonButton
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
            </LemonButton>
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
                            <LemonButton
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
                            </LemonButton>
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
                <Link to="/?path=/docs/lemon-ui-link" disableClientSideRouting>
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
                <LemonButton fullWidth>Kakapo</LemonButton>
                <LemonButton fullWidth>Kangaroo</LemonButton>
                <LemonButton fullWidth>Kingfisher</LemonButton>
                <LemonButton fullWidth>Koala</LemonButton>
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
                <LemonButton fullWidth>Kakapo</LemonButton>
                <LemonButton fullWidth>Kangaroo</LemonButton>
                <LemonButton fullWidth>Kingfisher</LemonButton>
                <LemonButton fullWidth>Koala</LemonButton>
            </>
        ),
        placement: 'bottom',
        matchWidth: true,
    },
}

export const WithVeryLongPopoverToTheBottom: PopoverStory = PopoverTemplate.bind({})
WithVeryLongPopoverToTheBottom.args = {
    ...Default.args,
    dropdown: {
        overlay: (
            <>
                {range(200).map((n) => (
                    <LemonButton key={n} fullWidth>
                        {n.toString()}
                    </LemonButton>
                ))}
            </>
        ),
        placement: 'bottom',
        matchWidth: true,
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
                    <LemonButton fullWidth>View</LemonButton>
                    <LemonButton fullWidth>Edit</LemonButton>
                    <LemonDivider />
                    <LemonButton status="danger" fullWidth>
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}

export const WithOverflowingContent = (): JSX.Element => {
    const longText = 'long text that will overflow the button by at least a little!'

    return (
        <div className="w-200 border p-2 rounded flex items-center gap-2 overflow-hidden">
            <LemonButton type="secondary">No shrink</LemonButton>
            <LemonButton type="secondary" icon={<IconLink />}>
                Small button
            </LemonButton>
            <LemonButton type="secondary" icon={<IconGear />} sideIcon={<IconLink />} truncate>
                Truncating {longText}
            </LemonButton>
            <LemonButton type="secondary">{longText}</LemonButton>
        </div>
    )
}
