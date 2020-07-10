import React from 'react'
import { EditAppUrls } from 'lib/components/AppEditorLink/EditAppUrls'

export function ToolbarModal(): React.ReactNode {
    return (
        <div>
            <h2>Select your site from the list:</h2>
            <EditAppUrls allowNavigation={true} />
        </div>
    )
}
