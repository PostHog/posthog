import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsAnalyticsScene,
}

export function ConversationsAnalyticsScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Resolution analytics</h1>
                <p className="text-muted-alt">
                    Graphs for AI containment, escalations, SLA breaches, and agent vs AI CSAT.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Chart placeholders for trends, funnels, and leaderboards.
            </div>
        </SceneContent>
    )
}
