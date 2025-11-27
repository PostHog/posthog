import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsTicketScene,
}

export function ConversationsTicketScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Ticket detail</h1>
                <p className="text-muted-alt">
                    Full transcript, AI/human events, and side-panel context for the selected ticket.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Chat timeline, customer context cards, and inline reply actions placeholder.
            </div>
        </SceneContent>
    )
}
