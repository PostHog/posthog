import { LemonButton } from 'lib/lemon-ui/LemonButton'
import type { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function GuestNotFoundScene(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
            <h1 className="text-2xl font-bold">This content isn't available to you</h1>
            <p className="text-muted">You don't have permission to view this page.</p>
            <LemonButton type="primary" to={urls.guest()}>
                Back to your shared content
            </LemonButton>
        </div>
    )
}

export const scene: SceneExport = {
    component: GuestNotFoundScene,
}
