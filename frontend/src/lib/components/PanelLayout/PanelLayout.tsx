import { IconMinus } from '@posthog/icons'
import { LemonButton, LemonButtonProps, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { LemonMenu, LemonMenuItem, LemonMenuProps } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { useState } from 'react'

type PanelContainerProps = {
    children: React.ReactNode
    primary: boolean
    className?: string
    column?: boolean
    title: string
    header?: JSX.Element | null
}

interface SettingsMenuProps extends Omit<LemonMenuProps, 'items' | 'children'> {
    label?: string
    items: LemonMenuItem[]
    icon?: JSX.Element
    isAvailable?: boolean
    whenUnavailable?: LemonMenuItem
    highlightWhenActive?: boolean
    closeOnClickInside?: boolean
}

type SettingsButtonProps = Omit<LemonButtonProps, 'status' | 'sideAction' | 'className'> & {
    tooltip?: string
    icon?: JSX.Element | null
    label?: JSX.Element | string
}

type SettingsToggleProps = SettingsButtonProps & {
    active: boolean
}

function PanelLayout({ className, ...props }: Omit<PanelContainerProps, 'primary' | 'title'>): JSX.Element {
    return <Container className={clsx(className, 'PanelLayout')} {...props} primary={false} />
}

function Container({ children, primary, className, column }: Omit<PanelContainerProps, 'title'>): JSX.Element {
    return (
        <div
            className={clsx(
                'flex',
                primary && 'flex-1',
                column ? 'flex-col gap-y-4' : 'gap-x-2',
                primary ? 'PanelLayout__container--primary' : 'PanelLayout__container--secondary',
                className
            )}
        >
            {children}
        </div>
    )
}

function Panel({ children, primary, className, title, header }: Omit<PanelContainerProps, 'column'>): JSX.Element {
    const [open, setOpen] = useState<boolean>(true)

    return (
        <div className={clsx(primary && 'flex-1', 'border bg-bg-light rounded-sm', className)}>
            <div
                className={clsx(
                    'flex flex-row w-full overflow-hidden bg-accent-3000 items-center justify-between',
                    open && 'border-b'
                )}
            >
                <span className="pl-1 font-medium">{title}</span>
                <div className="flex font-light text-xs">
                    {header}
                    <SettingsButton onClick={() => setOpen(!open)} icon={<IconMinus />} />
                </div>
            </div>
            {open ? children : null}
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

export function SettingsToggle({ tooltip, icon, label, active, ...props }: SettingsToggleProps): JSX.Element {
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
    return props.disabledReason ? button : <Tooltip title={tooltip}>{button}</Tooltip>
}

export function SettingsButton(props: SettingsButtonProps): JSX.Element {
    return <SettingsToggle active={false} {...props} />
}

PanelLayout.Panel = Panel
PanelLayout.Container = Container
PanelLayout.SettingsMenu = SettingsMenu
PanelLayout.SettingsToggle = SettingsToggle
PanelLayout.SettingsButton = SettingsButton

export default PanelLayout
