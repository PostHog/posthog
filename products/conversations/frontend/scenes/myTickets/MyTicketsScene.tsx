import { useValues } from 'kea'

import { Link, Spinner } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { NewTicket } from '../../components/SidePanel/NewTicket'
import { RestoreTickets } from '../../components/SidePanel/RestoreTickets'
import { sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { Ticket } from '../../components/SidePanel/Ticket'
import { TicketsList } from '../../components/SidePanel/TicketsList'
import { myTicketsSceneLogic } from './myTicketsSceneLogic'

// myTicketsSceneLogic rather than sidepanelTicketsLogic directly: the tickets logic never unmounts
// (the side panel tab icon keeps it alive), so only a scene-scoped logic gets a fresh mount, and
// with it a ticket refetch, on each navigation here
export const scene: SceneExport = {
    component: MyTicketsScene,
    logic: myTicketsSceneLogic,
}

// Sized against the viewport so the thread fills the page without the scene itself scrolling
const PANE_MIN_HEIGHT = 'min(400px, calc(100svh - 16rem))'
const PANE_MAX_HEIGHT = 'calc(100svh - 16rem)'

export function MyTicketsScene(): JSX.Element {
    const { view, currentTicket, newTicketDraftRevision, isBillingResolved } = useValues(sidepanelTicketsLogic)
    const { preflight } = useValues(preflightLogic)

    const hasIdentityMode = !!window.JS_POSTHOG_IDENTITY_DISTINCT_ID
    const isCloudOrDev = preflight?.cloud || process.env.NODE_ENV === 'development'

    if (!isCloudOrDev) {
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

    // canCreateTicket (which gates the create button and empty-state copy inside TicketsList) reads
    // as false until billing loads, so rendering earlier would flash the wrong eligibility state —
    // the side panel guards on the same condition
    if (!isBillingResolved) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Your tickets"
                    description="Support conversations with the PostHog team"
                    resourceType={{ type: 'conversation' }}
                />
                <div className="flex items-center justify-center h-40">
                    <Spinner />
                </div>
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
        pane = (
            <Ticket
                backButtonClassName="lg:hidden"
                messagesMinHeight={PANE_MIN_HEIGHT}
                messagesMaxHeight={PANE_MAX_HEIGHT}
            />
        )
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
            <div className="flex flex-col lg:flex-row items-start gap-4">
                <div className="w-full lg:w-96 shrink-0 overflow-y-auto max-h-[calc(100svh-16rem)]">
                    <TicketsList selectedTicketId={view === 'ticket' ? (currentTicket?.id ?? null) : null} />
                </div>
                <div className="flex-1 min-w-0 w-full">{pane}</div>
            </div>
        </SceneContent>
    )
}
