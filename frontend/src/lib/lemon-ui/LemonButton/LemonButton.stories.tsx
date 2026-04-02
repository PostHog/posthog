import type { Meta, StoryObj } from '@storybook/react'
import clsx from 'clsx'

import { IconGear, IconInfo, IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { IconCalculate, IconLink } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { capitalizeFirstLetter, range } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithDropdown,
    LemonButtonWithDropdownProps,
    LemonButtonWithoutSideActionProps,
} from './LemonButton'
import { More } from './More'

const statuses: LemonButtonProps['status'][] = ['default', 'alt', 'danger']
const types: LemonButtonProps['type'][] = ['primary', 'secondary', 'tertiary']

type Story = StoryObj<LemonButtonWithoutSideActionProps>
const meta: Meta<LemonButtonWithoutSideActionProps> = {
    title: 'Lemon UI/Lemon Button',
    component: LemonButton as any,
    tags: ['autodocs'],
    argTypes: {
        icon: {
            type: 'function',
        },
    },
}
export default meta

export const Default: Story = {
    args: {
        icon: <IconCalculate />,
        children: 'Click me',
    },
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

const TypesAndStatusesTemplate = (props: LemonButtonProps): JSX.Element => {
    return (
        <div className="deprecated-space-y-2">
            {types.map((type) => (
                <div key={type}>
                    <h5>type={capitalizeFirstLetter(type || '')}</h5>
                    <StatusesTemplate {...props} type={type} />
                </div>
            ))}
        </div>
    )
}

export const TypesAndStatuses: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-12">
                <div className="p-2 rounded-lg border">
                    <TypesAndStatusesTemplate />
                </div>
                <div className="p-2 bg-surface-primary rounded-lg border">
                    <TypesAndStatusesTemplate />
                </div>
            </div>
        )
    },
    args: { ...Default.args },
}

type PopoverStory = StoryObj<LemonButtonWithDropdownProps>

export const NoPadding: Story = {
    render: () => {
        return <StatusesTemplate noText noPadding />
    },
}

export const TextOnly: Story = {
    render: () => {
        return <StatusesTemplate type="secondary" icon={null} />
    },
}

export const Sizes: Story = {
    render: () => {
        const sizes: LemonButtonProps['size'][] = ['xxsmall', 'xsmall', 'small', 'medium', 'large']

        return (
            <div className="deprecated-space-y-2">
                {sizes.map((size) => (
                    <div key={size}>
                        <h5>size={size}</h5>
                        <StatusesTemplate size={size} type="secondary" />
                    </div>
                ))}
            </div>
        )
    },
}

export const SizesIconOnly: Story = {
    render: () => {
        const sizes: LemonButtonProps['size'][] = ['xxsmall', 'xsmall', 'small', 'medium', 'large']

        return (
            <div className="deprecated-space-y-2">
                {sizes.map((size) => (
                    <div key={size}>
                        <h5>size={size}</h5>
                        <StatusesTemplate size={size} type="secondary" noText />
                    </div>
                ))}
            </div>
        )
    },
}

export const DisabledWithReason: Story = {
    render: () => {
        return <StatusesTemplate disabledReason="You're not cool enough to click this." accommodateTooltip />
    },
}
// TODO: Add DisabledWithReason.play for a proper snapshot showcasing the tooltip

export const Loading: Story = {
    render: () => {
        return <TypesAndStatusesTemplate loading />
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const Active: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
                <p>
                    Sometimes you may need to keep the LemonButton in it's active state e.g. the hover state. This can
                    be done by setting the <code>active</code> property
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
    },
}

export const MenuButtons: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
                <div className="border rounded-lg flex flex-col p-2 deprecated-space-y-1">
                    <LemonButton active>Active item</LemonButton>
                    <LemonButton>Item 1</LemonButton>
                    <LemonButton>Item 2</LemonButton>
                </div>
            </div>
        )
    },
}

export const WithSideIcon: Story = {
    render: () => {
        return <StatusesTemplate sideIcon={<IconInfo />} />
    },
}

export const FullWidth: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
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
    },
}

export const WithSideAction: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
                {types.map((type) => (
                    <div key={type}>
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
                    </div>
                ))}
            </div>
        )
    },
}

export const WithButtonWrapper: Story = {
    render: () => {
        return (
            <div className="flex flex-col gap-2">
                <div className="border rounded-lg flex flex-col p-2 space-y-1">
                    <LemonButton
                        buttonWrapper={(button) => <div className="opacity-50">{button}</div>}
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'No wrapper around side action',
                            onClick: () => alert('Side action!'),
                        }}
                        active
                    >
                        wrapped with opacity 50
                    </LemonButton>
                    <LemonButton
                        buttonWrapper={(button) => <div className="opacity-20">{button}</div>}
                        sideAction={{
                            icon: <IconPlus />,
                            tooltip: 'No wrapper around side action',
                            onClick: () => alert('Side action!'),
                        }}
                    >
                        wrapped with opacity 20
                    </LemonButton>
                </div>
            </div>
        )
    },
}

export const AsLinks: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
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
    },
}

export const WithDropdownToTheRight: PopoverStory = {
    render: (props) => <LemonButtonWithDropdown {...props} />,
    args: {
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
    },
}

export const WithDropdownToTheBottom: PopoverStory = {
    render: (props) => <LemonButtonWithDropdown {...props} />,
    args: {
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
    },
}

export const WithVeryLongPopoverToTheBottom: PopoverStory = {
    render: (props) => <LemonButtonWithDropdown {...props} />,
    args: {
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
    },
}

export const WithTooltip: Story = {
    args: {
        ...Default.args,
        tooltip: (
            <>
                This is example with a link: <Link to="https://posthog.com">Go home</Link>
            </>
        ),
    },
}

export const WithTooltipPlacementAndArrowOffset: Story = {
    args: {
        ...Default.args,
        tooltip: (
            <>
                This is example with a link: <Link to="https://posthog.com">Go home</Link>
            </>
        ),
        tooltipPlacement: 'top-start',
        tooltipArrowOffset: 30,
    },
}

export const More_: Story = {
    render: () => {
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
    },
}

export const WithOverflowingContent: Story = {
    render: () => {
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
    },
}

export const WithAccessControl: Story = {
    render: () => {
        return (
            <div className="flex gap-2">
                <AccessControlAction
                    resourceType={AccessControlResourceType.Project}
                    minAccessLevel={AccessControlLevel.Admin}
                    userAccessLevel={AccessControlLevel.Admin}
                >
                    <LemonButton type="primary">Enabled (admin ≥ admin)</LemonButton>
                </AccessControlAction>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Project}
                    minAccessLevel={AccessControlLevel.Admin}
                    userAccessLevel={AccessControlLevel.Viewer}
                >
                    <LemonButton type="primary">Disabled (viewer {'<'} admin)</LemonButton>
                </AccessControlAction>
            </div>
        )
    },
}
