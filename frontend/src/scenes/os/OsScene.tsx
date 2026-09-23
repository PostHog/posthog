import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: OsScene,
}

// With OS_SHELL on, AuthenticatedShell renders the OS shell in place of any scene, so this
// component only renders when the flag is off or inside an OS window.
export function OsScene(): JSX.Element {
    return <NotFound object="page" />
}
