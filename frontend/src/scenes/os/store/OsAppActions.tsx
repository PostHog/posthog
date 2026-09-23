import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { isOsFrame } from '../bridge/osFrame'
import type { OsApp } from './osAppCatalog'
import { osAppStoreSceneLogic } from './osAppStoreSceneLogic'

export interface OsAppActionsProps {
    app: OsApp
    /** The listing page also offers Remove next to Open. */
    showRemove?: boolean
    size?: 'small' | 'medium'
}

/** Install and Preview, or Open and Remove, for one app. A button stays disabled while its write is in flight. */
export function OsAppActions({ app, showRemove = false, size = 'small' }: OsAppActionsProps): JSX.Element {
    const { installedKeys, pendingChanges } = useValues(osAppStoreSceneLogic)
    const { installApp, removeApp, openApp, previewApp } = useActions(osAppStoreSceneLogic)
    const installing = pendingChanges[app.key] === true
    const removing = pendingChanges[app.key] === false

    if (installing || !installedKeys.has(app.key)) {
        return (
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    size={size}
                    loading={installing}
                    onClick={() => installApp(app.key)}
                    data-attr="os-app-store-install"
                >
                    Install
                </LemonButton>
                {!installing && isOsFrame(window) && (
                    <LemonButton
                        type="secondary"
                        size={size}
                        onClick={() => previewApp(app)}
                        tooltip="Open the app in a window without adding it to your desktop"
                        data-attr="os-app-store-preview"
                    >
                        Preview
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonButton
                type="secondary"
                size={size}
                disabledReason={removing ? 'Removing this app' : undefined}
                onClick={() => openApp(app)}
                data-attr="os-app-store-open"
            >
                Open
            </LemonButton>
            {showRemove && (
                <LemonButton
                    type="secondary"
                    status="danger"
                    size={size}
                    loading={removing}
                    onClick={() => removeApp(app.key)}
                    data-attr="os-app-store-remove"
                >
                    Remove
                </LemonButton>
            )}
        </div>
    )
}
