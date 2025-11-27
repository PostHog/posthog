import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ScenesTabs } from '../../components/ScenesTabs'

export const scene: SceneExport = {
    component: ConversationsTicketsScene,
}

export function ConversationsTicketsScene(): JSX.Element {
    return (
        <SceneContent className="space-y-4">
            <ScenesTabs />
            <section className="space-y-1">
                <h1 className="text-2xl font-semibold">Ticket list</h1>
                <p className="text-muted-alt">
                    Unified inbox with filters, status pills, and AI vs human resolution indicators.
                </p>
            </section>
            <div className="rounded border border-dashed p-4 text-muted">
                Table/grid for tickets, filter bar, and bulk actions placeholder.
            </div>
        </SceneContent>
    )
}
