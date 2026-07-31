import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewTicket } from '../../components/SidePanel/NewTicket'
import { RestoreTickets } from '../../components/SidePanel/RestoreTickets'
import { sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { Ticket } from '../../components/SidePanel/Ticket'
import { TicketsList } from '../../components/SidePanel/TicketsList'

export const scene: SceneExport = {
    component: MyTicketsScene,
    logic: sidepanelTicketsLogic,
}

// Sized against the viewport so the thread fills the page without the scene itself scrolling
const PANE_MIN_HEIGHT = 'min(400px, calc(100svh - 16rem))'
const PANE_MAX_HEIGHT = 'calc(100svh - 16rem)'

export function MyTicketsScene(): JSX.Element {
    const { view, currentTicket, newTicketDraftRevision, isEnabled } = useValues(sidepanelTicketsLogic)
    const { preflight } = useValues(preflightLogic)

    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID
    const isCloudOrDev = preflight?.cloud || process.env.NODE_ENV === 'development'

    if (!isEnabled || !isCloudOrDev) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Your tickets"
                    description="Support conversations with the PostHog team"
                    resourceType={{ type: 'conversation' }}
                />
                <p className="text-muted-alt">
                    Support tickets aren't available on this instance. You can ask the{' '}
                    <Link to="https://posthog.com/questions" target="_blank">
                        community forum
                    </Link>{' '}
                    instead.
                </p>
            </SceneContent>
        )
    }

    let pane: JSX.Element
    if (view === 'new') {
        // Key on the draft revision so a prefill injected while the composer is already open
        // remounts the editor (it only reads initial content at creation)
        pane = <NewTicket key={newTicketDraftRevision} />
    } else if (view === 'restore' && !hasIdentityMode) {
        pane = <RestoreTickets />
    } else if (view === 'ticket' && currentTicket) {
        pane = <Ticket showBackButton={false} messagesMinHeight={PANE_MIN_HEIGHT} messagesMaxHeight={PANE_MAX_HEIGHT} />
    } else {
        pane = (
            <div className="flex items-center justify-center border border-dashed rounded-lg text-muted-alt min-h-[min(400px,calc(100svh-16rem))]">
                Select a ticket to view the conversation
            </div>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Your tickets"
                description="Support conversations with the PostHog team"
                resourceType={{ type: 'conversation' }}
            />
            <div className="flex items-start gap-4">
                <div className="w-96 shrink-0 overflow-y-auto max-h-[calc(100svh-16rem)]">
                    <TicketsList />
                </div>
                <div className="flex-1 min-w-0">{pane}</div>
            </div>
        </SceneContent>
    )
}
