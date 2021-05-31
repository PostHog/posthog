import './ToolbarModal.scss'
import React from 'react'
import { useValues } from 'kea'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { userLogic } from 'scenes/userLogic'
import { ToolbarSettings } from 'scenes/project/Settings/ToolbarSettings'

export function ToolbarModal(): JSX.Element {
    const { user } = useValues(userLogic)
    const toolbarEnabled = user?.toolbar_mode !== 'disabled'

    return (
        <div className="toolbar-modal">
            {!toolbarEnabled ? (
                <>
                    <h2>Enable the Toolbar to continue</h2>
                    <ToolbarSettings />
                </>
            ) : (
                <>
                    <h2>Toolbar – Permitted Domains/URLs</h2>
                    <p>
                        Make sure you're using the snippet or the latest <code>posthog-js</code> version.
                        <br />
                        Clicking a URL launches it with the Toolbar.
                    </p>
                    <EditAppUrls allowNavigation />
                </>
            )}
        </div>
    )
}
