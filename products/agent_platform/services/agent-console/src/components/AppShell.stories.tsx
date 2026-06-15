/**
 * Whole-shell stories — render the real `<AppShell>` against the real
 * page clients with MSW serving the API surface (see
 * `.storybook/mocks/handlers.ts`) and the `next/navigation` + `next/link`
 * mocks driving a story-local router.
 *
 * The `NavigableShell` story is the primary review surface: click
 * around the sidebar, agent cards, tabs, session rows — the story-local
 * router resolves the current path to the right segment and updates
 * `useParams()` / `useSearchParams()` so every page component renders
 * as if it were running under Next.js. `focus_*` client tools the chat
 * dock calls go through `router.push()` too, so they soft-nav rather
 * than triggering a re-render.
 */

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useMemo, useSyncExternalStore } from 'react'

import { getSnapshot, navigate, reset, setParams, subscribe } from '../../.storybook/mocks/router-store'
import { AgentsListClient } from '../../app/agents-list-client'
import { ConfigurationSegment } from '../../app/agents/[slug]/configuration/configuration-client'
import { MemorySegment } from '../../app/agents/[slug]/memory/memory-client'
import { OverviewSegment } from '../../app/agents/[slug]/overview-client'
import { SessionsSegment } from '../../app/agents/[slug]/sessions/sessions-client'
import { BillingClient } from '../../app/billing/billing-client'
import { RegistryClient } from '../../app/registry/registry-client'
import { AgentProvider } from './agent-context'
import { AgentLayout } from './AgentLayout'
import { AppShell } from './AppShell'
import { AgentDetailSkeleton } from './PageSkeletons'

/**
 * Provider → layout → segment, mirroring the production
 * `app/agents/[slug]/layout.tsx` shape. The segment body is whichever
 * route the story-local router matched.
 */
function AgentDetailSurface({ slug, children }: { slug: string; children: React.ReactNode }): React.ReactElement {
    return (
        <AgentProvider
            slug={slug}
            fallback={<AgentDetailSkeleton />}
            notFoundFallback={<div className="px-6 py-6 text-sm text-muted-foreground">Agent not found.</div>}
            errorFallback={(err) => (
                <div className="px-6 py-6 text-sm text-destructive-foreground">Failed to load: {err.message}</div>
            )}
        >
            <AgentLayout>{children}</AgentLayout>
        </AgentProvider>
    )
}

/**
 * Resolve the current path to a page. Mirrors `app/` route layout:
 *
 *   /                                  → agents list
 *   /agents                            → agents list
 *   /agents/<slug>                     → overview
 *   /agents/<slug>/configuration       → configuration
 *   /agents/<slug>/memory              → memory
 *   /agents/<slug>/sessions            → sessions
 *   /registry                          → registry
 *   /billing                           → billing
 */
function matchRoute(pathname: string): {
    element: React.ReactElement
    params: Record<string, string>
} {
    if (pathname === '/' || pathname === '/agents') {
        return { element: <AgentsListClient />, params: {} }
    }
    const agent = /^\/agents\/([^/]+)(?:\/([^/?#]+))?\/?$/.exec(pathname)
    if (agent) {
        const slug = agent[1]
        const tab = agent[2]
        const params = { slug }
        const segment =
            tab === 'configuration' ? (
                <ConfigurationSegment />
            ) : tab === 'memory' ? (
                <MemorySegment />
            ) : tab === 'sessions' ? (
                <SessionsSegment />
            ) : (
                <OverviewSegment />
            )
        return { element: <AgentDetailSurface slug={slug}>{segment}</AgentDetailSurface>, params }
    }
    if (pathname === '/registry' || pathname.startsWith('/registry/')) {
        return { element: <RegistryClient />, params: {} }
    }
    if (pathname === '/billing') {
        return { element: <BillingClient />, params: {} }
    }
    return {
        element: (
            <div className="px-6 py-6 text-sm text-muted-foreground">
                No route matched <code className="font-mono text-foreground">{pathname}</code>.
            </div>
        ),
        params: {},
    }
}

/**
 * Subscribes to the story-local router, resolves the current path to a
 * page, and pushes the matched dynamic params back into the store so
 * `useParams()` returns the right values inside the page tree.
 */
function StoryRoutes({ initialPath }: { initialPath: string }): React.ReactElement {
    // One-time reset so the story starts at its declared initialPath
    // even after a previous story left the store mid-navigation.
    useEffect(() => {
        reset(initialPath)
    }, [initialPath])

    const path = useSyncExternalStore(
        subscribe,
        () => getSnapshot().path,
        () => initialPath
    )
    const pathname = path.split('?')[0]

    const { element, params } = useMemo(() => matchRoute(pathname), [pathname])

    useEffect(() => {
        setParams(params)
    }, [params])

    return element
}

const meta: Meta<typeof AppShell> = {
    title: 'Agent console/Shell (full surface)',
    component: AppShell,
    parameters: { layout: 'fullscreen' },
}

export default meta
type Story = StoryObj<typeof AppShell>

/**
 * Fully navigable console. Start on the agents list, click into an
 * agent, switch tabs, navigate to registry / billing from the sidebar
 * — everything is real-component + MSW-mocked-API + story-local
 * router. The dock's `focus_*` tools also drive the same router, so
 * the chat-side navigation works too.
 */
export const NavigableShell: Story = {
    render: () => (
        <AppShell>
            <StoryRoutes initialPath="/agents" />
        </AppShell>
    ),
}

/** Same shell, but start directly on the concierge's configuration tab. */
export const StartOnConfiguration: Story = {
    render: () => (
        <AppShell>
            <StoryRoutes initialPath="/agents/release-concierge/configuration" />
        </AppShell>
    ),
}

/** Same shell, but start directly on the weekly-digest sessions tab. */
export const StartOnSessions: Story = {
    render: () => (
        <AppShell>
            <StoryRoutes initialPath="/agents/weekly-digest/sessions" />
        </AppShell>
    ),
}

// The old single-render stories are kept as quick "open exactly one page"
// surfaces — useful when you want to skip the list-to-detail navigation
// and pin a specific landing point for visual review.

export const AgentsList: Story = {
    render: () => (
        <AppShell>
            <AgentsListClient />
        </AppShell>
    ),
}

export const AgentDetail_WeeklyDigest: Story = {
    render: () => {
        // Seed the router so any nested `useParams()` reads the right slug.
        navigate('/agents/weekly-digest')
        setParams({ slug: 'weekly-digest' })
        return (
            <AppShell>
                <AgentDetailSurface slug="weekly-digest">
                    <OverviewSegment />
                </AgentDetailSurface>
            </AppShell>
        )
    },
}

export const AgentDetail_ReleaseConcierge: Story = {
    render: () => {
        navigate('/agents/release-concierge')
        setParams({ slug: 'release-concierge' })
        return (
            <AppShell>
                <AgentDetailSurface slug="release-concierge">
                    <OverviewSegment />
                </AgentDetailSurface>
            </AppShell>
        )
    },
}
