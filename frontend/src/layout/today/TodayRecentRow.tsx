import { useMemo } from 'react'

import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'

import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

/** A record a person opened or pinned in a rail pane, with a hover card that says what opening it shows. */
export function TodayRecentRow({
    value,
    name,
    href,
    icon,
    description,
    active,
    action,
    dataAttr,
}: {
    value: string
    name: string
    href: string
    icon: JSX.Element
    description: string
    active: boolean
    action?: JSX.Element
    dataAttr: string
}): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({ kind: 'explainer', label: name, icon, description }),
        [name, icon, description]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={value}
                label={name}
                icon={icon}
                to={href}
                active={active}
                action={action}
                dataAttr={dataAttr}
            />
        </TodayPreviewTrigger>
    )
}
