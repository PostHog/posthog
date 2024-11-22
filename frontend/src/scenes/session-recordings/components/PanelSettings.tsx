import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

/**
 * TODO the lemon button font only has 700 and 800 weights available.
 * Ideally these buttons would use more like 400 and 500 weights.
 * or even 300 and 400 weights.
 * when inactive / active respectively.
 */

export function SettingsMenu({
    label,
    items,
    icon,
    ...props
}: Omit<LemonMenuProps, 'items' | 'children'> & {
    items: LemonMenuItem[]
    label: JSX.Element | string
    icon: JSX.Element
}): JSX.Element {
    const active = items.some((cf) => !!cf.active)
    return (
        <LemonMenu buttonSize="xsmall" closeOnClickInside={false} items={items} {...props}>
            <LemonButton status={active ? 'danger' : 'default'} size="xsmall" icon={icon}>
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
}: Omit<LemonButtonProps, 'status' | 'sideAction'> & {
    active: boolean
    title: string
    icon?: JSX.Element | null
    label: JSX.Element | string
}): JSX.Element {
    const button = (
        <LemonButton icon={icon} size="xsmall" status={active ? 'danger' : 'default'} {...props}>
            {label}
        </LemonButton>
    )

    // otherwise the tooltip shows instead of the disabled reason
    return props.disabledReason ? button : <Tooltip title={title}>{button}</Tooltip>
}
