import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
}

export function SettingsMenu({
    label,
    items,
    icon,
    isAvailable = true,
    highlightWhenActive = true,
    whenUnavailable,
    ...props
}: SettingsMenuProps): JSX.Element {
    const active = items.some((cf) => !!cf.active)
    return (
        <LemonMenu
            buttonSize="xsmall"
            closeOnClickInside={false}
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

export function SettingsToggle({
    title,
    icon,
    label,
    active,
    ...props
}: Omit<LemonButtonProps, 'status' | 'sideAction' | 'className'> & {
    active: boolean
    title: string
    icon?: JSX.Element | null
    label: JSX.Element | string
}): JSX.Element {
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
