import './ToolbarModal.scss'
import React from 'react'
import { useValues } from 'kea'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'
import { HogIcon } from 'lib/icons/HogIcon'
import { userLogic } from 'scenes/userLogic'
import { ToolbarSettings } from 'scenes/setup/ToolbarSettings'

export function ToolbarModal(): React.ReactNode {
    const { user } = useValues(userLogic)
    const toolbarEnabled = user?.toolbar_mode === 'toolbar'
    const appUrls = user?.team?.app_urls || []

    return (
        <div className="toolbar-modal">
            {!toolbarEnabled ? (
                <>
                    <HogIcon className="hog-icon" color="#aaaaaa" eyeColor="#ffffff" />
                    <h2>Toolbar Beta - Opt In</h2>
                    <ToolbarSettings />
                </>
            ) : (
                <>
                    <HogIcon className="hog-icon" />
                    {appUrls.length === 0 ? (
                        <h2>Please add your site!</h2>
                    ) : (
                        <>
                            <h2>Select your site from the list:</h2>
                            <p>
                                Make sure it's using the latest JS snippet or <code>posthog-js</code> version!
                            </p>
                        </>
                    )}
                    <EditAppUrls allowNavigation={true} />
                    <a
                        className="toolbar-help"
                        href="https://github.com/PostHog/posthog/issues/1129"
                        target="_blank"
                        rel="noreferrer noopener"
                    >
                        Share Feedback!
                    </a>
                </>
            )}
        </div>
    )
}
