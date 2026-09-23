import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { OsAppIcon } from '../icons/OsAppIcon'
import type { OsApp } from './osAppCatalog'
import { osAppPreviewLogic } from './osAppPreviewLogic'

export function OsAppPreviewBar({ app }: { app: OsApp }): JSX.Element {
    const { installApp } = useActions(osAppPreviewLogic)

    return (
        <div
            className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-primary bg-surface-secondary px-3 py-1 text-xs"
            data-attr="os-app-preview-bar"
        >
            <OsAppIcon app={app} size="custom" className="size-5" />
            <span className="min-w-0 flex-1 truncate">
                Previewing <strong>{app.name}</strong>. Install it to add it to your desktop.
            </span>
            <LemonButton
                type="primary"
                size="xsmall"
                onClick={() => installApp(app.key)}
                data-attr="os-app-preview-install"
            >
                Install
            </LemonButton>
        </div>
    )
}
