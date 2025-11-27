import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsSettingsScene,
}

export function ConversationsSettingsScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Conversations settings</h1>
                <p className="text-muted-alt">
                    Configure Slack connect, widget defaults, and AI assistance toggles per channel.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Integrations list, channel toggles, and fallback policy editor placeholder.
            </div>
        </SceneContent>
    )
}
