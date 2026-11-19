import { useActions, useValues } from 'kea'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'

/** Lists the project's authorized URLs, so the user can open a page the toolbar runs on. */
export function ExtensionAuthorizedUrlLinks(): JSX.Element | null {
    const { openableAuthorizedUrls, user } = useValues(extensionPanelLogic)
    const { openAuthorizedUrl } = useActions(extensionPanelLogic)

    if (openableAuthorizedUrls.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="text-xs font-semibold text-secondary">
                Authorized URLs for {user?.team.name ?? 'this project'}
            </div>
            <ul className="flex flex-col gap-px m-0 p-0 list-none">
                {openableAuthorizedUrls.map((url) => (
                    <li key={url}>
                        <LemonButton
                            fullWidth
                            size="small"
                            sideIcon={<IconOpenInNew />}
                            onClick={() => openAuthorizedUrl(url)}
                            tooltip="Open in a new tab"
                            data-attr="toolbar-extension-open-authorized-url"
                        >
                            <span className="truncate">{url}</span>
                        </LemonButton>
                    </li>
                ))}
            </ul>
        </div>
    )
}
