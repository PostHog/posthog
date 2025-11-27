import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsGuidanceScene,
}

export function ConversationsGuidanceScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Guidance & guardrails</h1>
                <p className="text-muted-alt">Configure tone, escalation rules, and rollout plans for AI assistance.</p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Form builder for guidance packs and escalation triggers placeholder.
            </div>
        </SceneContent>
    )
}
