import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { osFrameSrc } from '../bridge/osFrame'
import { OsWindow } from '../windows/OsWindow'

export function OsShell(): JSX.Element {
    const { activeSceneId, sceneConfig } = useValues(sceneLogic)
    // The URL the page opened on becomes the window. Later changes to this page's URL must not reload it.
    const [src] = useState(() => osFrameSrc(router.values.location, window.location.origin))

    return (
        <div className="flex flex-col h-screen w-full p-4 bg-surface-tertiary" data-attr="os-shell">
            {src && activeSceneId !== Scene.Os && (
                <OsWindow id="focused" title={sceneConfig?.name ?? 'PostHog'} src={src} />
            )}
        </div>
    )
}
