import clsx from 'clsx'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PropsWithChildren } from 'react'

/**
 * TODO the lemon button font only has 700 and 800 weights available.
 * Ideally these buttons would use more like 400 and 500 weights.
 * or even 300 and 400 weights.
 * when inactive / active respectively.
 */

interface SettingsMenuProps extends Omit<LemonMenuProps, 'items' | 'children'> {
    label?: string
    items: LemonMenuItem[]
    icon?: JSX.Element
    isAvailable?: boolean
    whenUnavailable?: LemonMenuItem
    highlightWhenActive?: boolean
    closeOnClickInside?: boolean
}

export function SettingsBar({
    children,
    border,
    className,
}: PropsWithChildren<{
    border: 'bottom' | 'top' | 'none'
    className?: string
}>): JSX.Element {
    return (
        <div
            className={clsx(
                border === 'bottom' && 'border-b',
                border === 'top' && 'border-t',
                'flex flex-row w-full overflow-hidden font-light text-small bg-bg-3000',
                className
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
                className="rounded-[0px]"
                status={highlightWhenActive && active ? 'danger' : 'default'}
                size="xsmall"
                icon={icon}
            >
                {label}
            </LemonButton>
        </LemonMenu>
    )
}

type SettingsButtonProps = Omit<LemonButtonProps, 'status' | 'sideAction' | 'className'> & {
    title?: string
    icon?: JSX.Element | null
    label: JSX.Element | string
}

type SettingsToggleProps = SettingsButtonProps & {
    active: boolean
}

export function SettingsButton(props: SettingsButtonProps): JSX.Element {
    return <SettingsToggle active={false} {...props} />
}

export function SettingsToggle({ title, icon, label, active, ...props }: SettingsToggleProps): JSX.Element {
    const button = (
        <LemonButton
            className="rounded-[0px]"
            icon={icon}
            size="xsmall"
            status={active ? 'danger' : 'default'}
            {...props}
        >
            {label}
        </LemonButton>
    )

    // otherwise the tooltip shows instead of the disabled reason
    return props.disabledReason ? button : <Tooltip title={title}>{button}</Tooltip>
}
