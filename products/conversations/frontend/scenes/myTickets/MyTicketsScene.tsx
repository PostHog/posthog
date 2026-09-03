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
                fillParent
                backButtonClassName="@min-[48rem]/main-content:hidden"
                messagesMinHeight="300px"
                messagesMaxHeight="none"
            />
        )
    } else {
        pane = (
            <div className="flex items-center justify-center border border-dashed rounded-lg text-muted-alt h-full min-h-80">
                Select a ticket to view the conversation
            </div>
        )
    }

    return (
        <SceneContent className="flex-1 min-h-0 pb-4">
            <SceneTitleSection
                name="Your tickets"
                description="Support conversations with the PostHog team"
                resourceType={{ type: 'conversation' }}
            />
            {/* Overflow clipping is only safe in the side-by-side row, where the list has a bounded
                height and its inner scroller can run. Stacked, the list is content-sized; clipping
                here would hide tickets and leave the thread with no height. */}
            <div className="flex flex-col gap-4 @min-[48rem]/main-content:flex-row @min-[48rem]/main-content:flex-1 @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:overflow-hidden">
                <div className="w-full @min-[48rem]/main-content:w-96 @min-[48rem]/main-content:shrink-0 @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:h-full @min-[48rem]/main-content:overflow-hidden">
                    <TicketsList selectedTicketId={view === 'ticket' ? (currentTicket?.id ?? null) : null} />
                </div>
                <div className="w-full min-w-0 min-h-80 @min-[48rem]/main-content:flex-1 @min-[48rem]/main-content:min-h-0 @min-[48rem]/main-content:flex @min-[48rem]/main-content:flex-col">
                    {pane}
                </div>
            </div>
        </SceneContent>
    )
}
