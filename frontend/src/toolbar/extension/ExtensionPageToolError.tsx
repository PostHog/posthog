import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { canRequestHostPermission } from './extensionBrowser'
import { extensionPageToolsLogic } from './extensionPageToolsLogic'

/** Explains why a page tool couldn't run. */
export function ExtensionPageToolError(): JSX.Element | null {
    const { pageToolError } = useValues(extensionPageToolsLogic)
    const { requestPageAccess } = useActions(extensionPageToolsLogic)

    if (pageToolError === 'no-inspected-element') {
        return <div className="text-warning text-xs">Select an element in the Elements panel first.</div>
    }
    if (pageToolError === 'no-page-access') {
        return (
            <div className="flex flex-col gap-1 text-warning text-xs">
                <span>
                    The extension can't reach this site. Allow it on this site, or turn on site access for the PostHog
                    toolbar in your browser's extension settings.
                </span>
                {canRequestHostPermission() && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={requestPageAccess}
                        data-attr="toolbar-extension-allow-page"
                    >
                        Allow on this site
                    </LemonButton>
                )}
            </div>
        )
    }
    return null
}
