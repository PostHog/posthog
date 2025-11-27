import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsDashboardScene,
}

export function ConversationsDashboardScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Conversations overview</h1>
                <p className="text-muted-alt">Monitor AI containment, escalations, and SLA risks in one place.</p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                KPI tiles, escalation pods, and recent content/guidance edits will render here.
            </div>
        </SceneContent>
    )
}
