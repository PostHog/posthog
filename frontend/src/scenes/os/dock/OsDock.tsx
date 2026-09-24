import './OsDock.scss'

import { useValues } from 'kea'
import { CSSProperties } from 'react'

import { IconBrowser, IconStore } from '@posthog/icons'

import { OsAppIcon } from '../icons/OsAppIcon'
import { osDockLogic } from './osDockLogic'
import { OsDockTile } from './OsDockTile'

export function OsDock(): JSX.Element {
    const { dock } = useValues(osDockLogic)

    return (
        <nav
            aria-label="Dock"
            className="order-last flex justify-center pt-2 pointer-events-none"
            data-os-scheme="primary"
            data-attr="os-dock"
        >
            <ul
                className="OsDock__shelf"
                // oxlint-disable-next-line react/forbid-dom-props
                style={{ '--os-dock-count': dock.apps.length + 2 } as CSSProperties}
            >
                <OsDockTile
                    item={dock.store}
                    icon={
                        <OsAppIcon
                            app={null}
                            icon={<IconStore />}
                            color="var(--brand-red)"
                            size="custom"
                            className="OsDock__icon"
                        />
                    }
                    data-attr="os-dock-app-store"
                />
                {dock.apps.length > 0 && <li className="OsDock__divider" aria-hidden />}
                {dock.apps.map((item) => (
                    <OsDockTile
                        key={item.key}
                        item={item}
                        icon={
                            <OsAppIcon
                                app={item.app}
                                icon={item.app ? undefined : <IconBrowser />}
                                size="custom"
                                className="OsDock__icon"
                            />
                        }
                        data-attr={item.app ? 'os-dock-app' : 'os-dock-window'}
                    />
                ))}
            </ul>
        </nav>
    )
}
