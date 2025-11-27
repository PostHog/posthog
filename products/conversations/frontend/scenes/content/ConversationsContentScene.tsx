import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsContentScene,
}

export function ConversationsContentScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Content library</h1>
                <p className="text-muted-alt">
                    Manage procedures, snippets, and audience targeting rules that power AI answers.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Table of knowledge entries, toggles, and targeting controls placeholder.
            </div>
        </SceneContent>
    )
}
