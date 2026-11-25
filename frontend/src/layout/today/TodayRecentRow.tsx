import { useMemo } from 'react'

import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'

import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodayRecentTypeCopy, recentRowKey } from './todayRecents'

/**
 * A record a person opened or pinned in a rail pane: its type after the name, a pin toggle on hover, and a hover card
 * that says what opening it shows.
 */
export function TodayRecentRow({
    recent,
    icon,
    typeCopy,
    active,
    dataAttr,
}: {
    recent: { type: string; name: string; href: string; ref?: string }
    icon: JSX.Element
    typeCopy: TodayRecentTypeCopy
    active: boolean
    dataAttr: string
}): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({ kind: 'explainer', label: recent.name, icon, description: typeCopy.description }),
        [recent.name, icon, typeCopy.description]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={recentRowKey(recent.href)}
                label={recent.name}
                icon={icon}
                meta={typeCopy.label}
                to={recent.href}
                active={active}
                action={
                    <SidebarPinButton
                        target={{ type: recent.type, ref: recent.ref, name: recent.name, href: recent.href }}
                        dataAttr={`${dataAttr}-pin`}
                    />
                }
                dataAttr={dataAttr}
            />
        </TodayPreviewTrigger>
    )
}
