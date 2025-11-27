import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsPlaygroundScene,
}

export function ConversationsPlaygroundScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Playground</h1>
                <p className="text-muted-alt">
                    Test prompts, review retrieval traces, and compare guidance/content stacks before deploying.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Prompt input, scenario selector, and trace output placeholder.
            </div>
        </SceneContent>
    )
}
