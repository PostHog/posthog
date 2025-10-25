import './PanelSettings.scss'

import { PropsWithChildren } from 'react'

import {
    LemonButton,
    LemonButtonWithSideActionProps,
    LemonButtonWithoutSideActionProps,
} from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

/**
 * TODO the lemon button font only has 700 and 800 weights available.
 * Ideally these buttons would use more like 400 and 500 weights.
 * or even 300 and 400 weights.
 * when inactive / active respectively.
 */

interface SettingsMenuProps extends Omit<LemonMenuProps, 'items' | 'children'> {
    label?: string | React.ReactElement
    items: LemonMenuItem[]
    icon?: JSX.Element
    isAvailable?: boolean
    whenUnavailable?: LemonMenuItem
    highlightWhenActive?: boolean
    closeOnClickInside?: boolean
    /**
     * Whether the button should be rounded or not
     */
    rounded?: boolean
    disabledReason?: string
}

export function SettingsBar({
    children,
    border,
    className,
}: PropsWithChildren<{
    border: 'bottom' | 'top' | 'all' | 'none'
    className?: string
}>): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-row w-full overflow-hidden font-light text-xs bg-primary items-center',
                className,
                {
                    'border-b': ['bottom', 'all'].includes(border),
                    'border-t': ['top', 'all'].includes(border),
                }
            )}
        >
            {children}
        </div>
    )
}

export function SettingsMenu({
    label,
    items,
    icon,
    isAvailable = true,
    closeOnClickInside = true,
    highlightWhenActive = true,
    whenUnavailable,
    rounded = false,
    disabledReason,
    ...props
}: SettingsMenuProps): JSX.Element {
    const active = items.some((cf) => !!cf.active)
    return (
        <LemonMenu
            buttonSize="xsmall"
            closeOnClickInside={closeOnClickInside}
            items={isAvailable ? items : whenUnavailable ? [whenUnavailable] : []}
            {...props}
        >
            <LemonButton
                className={cn(rounded ? 'rounded' : 'rounded-[0px]')}
                status={highlightWhenActive && active ? 'danger' : 'default'}
                size="xsmall"
                icon={icon}
                disabledReason={disabledReason}
            >
                {label}
            </LemonButton>
        </LemonMenu>
    )
}

type SettingsButtonProps = (
    | Omit<LemonButtonWithoutSideActionProps, 'status' | 'className'>
    | Omit<LemonButtonWithSideActionProps, 'status' | 'className'>
) & {
    title?: string
    icon?: JSX.Element | null
    label: JSX.Element | string
}

type SettingsToggleProps = SettingsButtonProps & {
    active: boolean
    rounded?: boolean
}

export function SettingsButton(props: SettingsButtonProps): JSX.Element {
    return <SettingsToggle active={false} {...props} />
}

export function SettingsToggle({ title, icon, label, active, rounded, ...props }: SettingsToggleProps): JSX.Element {
    const button = (
        <LemonButton
            className={cn(rounded ? 'rounded' : 'rounded-[0px]')}
            icon={icon}
            size="xsmall"
            status={active ? 'danger' : 'default'}
            {...props}
        >
            {label}
        </LemonButton>
    )

    // otherwise the tooltip shows instead of the disabled reason
    return (
        <div className={cn(rounded ? 'SettingsBar--button--rounded' : 'SettingsBar--button--square')}>
            {props.disabledReason ? button : <Tooltip title={title}>{button}</Tooltip>}
        </div>
    )
}
