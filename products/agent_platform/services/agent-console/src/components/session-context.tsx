/**
 * Browser-side session context — wraps `/api/auth/me` so any component
 * can read the authenticated user's team id, name, email, etc. without
 * each having to fetch it.
 *
 * Loaded once on app mount. Authenticated requests downstream
 * (`apiClient`) read `teamId` via `useSessionTeamId()` and pass it on
 * the URL — no more hardcoded project id.
 *
 * When `authenticated: false` is returned, the UI renders an unauthed
 * landing surface (see `<SessionGate>`) with a "Sign in with PostHog"
 * button rather than bouncing the browser through the OAuth flow.
 */

'use client'

import { Loader2Icon } from 'lucide-react'
import { usePathname, useSearchParams } from 'next/navigation'
import { createContext, useContext, useEffect, useState } from 'react'

import { PostHogMark } from './PostHogMark'

export interface SessionInfo {
    authenticated: boolean
    teamId: number | null
    /** Whatever else `/oauth/userinfo` returned — `sub`, `email`, `name`, etc. */
    [key: string]: unknown
}

interface SessionStore {
    info: SessionInfo | null
    loading: boolean
    error: Error | null
}

const SessionCtx = createContext<SessionStore | null>(null)

export function SessionProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    const [info, setInfo] = useState<SessionInfo | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const res = await fetch('/api/auth/me', { headers: { Accept: 'application/json' } })
                if (!res.ok) {
                    throw new Error(`auth/me ${res.status}`)
                }
                const body = (await res.json()) as SessionInfo
                if (!cancelled) {
                    setInfo(body)
                    setLoading(false)
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err : new Error(String(err)))
                    setLoading(false)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [])

    return <SessionCtx.Provider value={{ info, loading, error }}>{children}</SessionCtx.Provider>
}

export function useSession(): SessionStore {
    const store = useContext(SessionCtx)
    if (!store) {
        return { info: null, loading: false, error: null }
    }
    return store
}

export function useSessionTeamId(): number | null {
    const { info } = useSession()
    return info?.teamId ?? null
}

export interface SessionUser {
    email: string | null
    firstName: string | null
    lastName: string | null
    /** Convenience: 2-char uppercase initials from the name or email. */
    initials: string
    /** Convenience: name when present, falling back to the email's local part. */
    displayName: string
}

export function useSessionUser(): SessionUser | null {
    const { info } = useSession()
    const profile = (info?.profile ?? null) as {
        email?: string | null
        first_name?: string | null
        last_name?: string | null
    } | null
    if (!profile) {
        return null
    }
    const firstName = profile.first_name ?? null
    const lastName = profile.last_name ?? null
    const email = profile.email ?? null
    const displayName = [firstName, lastName].filter(Boolean).join(' ').trim() || email?.split('@')[0] || 'Account'
    const initials = computeInitials(firstName, lastName, email)
    return { email, firstName, lastName, initials, displayName }
}

function computeInitials(first: string | null, last: string | null, email: string | null): string {
    const fromName = [first, last]
        .filter((s): s is string => !!s && s.length > 0)
        .map((s) => s[0]!.toUpperCase())
        .join('')
    if (fromName.length > 0) {
        return fromName.slice(0, 2)
    }
    if (email) {
        return email.slice(0, 2).toUpperCase()
    }
    return '??'
}

export function usePosthogBaseUrl(): string | null {
    const { info } = useSession()
    const url = (info as { posthogBaseUrl?: string } | null)?.posthogBaseUrl ?? null
    return url
}

interface AgentIngressInfo {
    routingMode: 'path' | 'domain'
    domainSuffix: string | null
    pathBaseUrl: string | null
}

/**
 * Fallback ingress base URL for an agent, built from the console's own
 * routing config (`/api/auth/me` → `agentIngress`). Django's
 * `agent.ingress_base_url` is the canonical source; use this only when
 * that's null — typically local dev, where Django has no
 * `AGENT_INGRESS_PUBLIC_URL` but the ingress is reachable at the
 * console's own `POSTHOG_AGENTS_BASE` (`http://localhost:3030`).
 */
export function useAgentIngressFallbackBaseUrl(slug: string): string | null {
    const { info } = useSession()
    const ingress = (info as { agentIngress?: AgentIngressInfo } | null)?.agentIngress ?? null
    if (!ingress || !slug) {
        return null
    }
    if (ingress.routingMode === 'domain') {
        return ingress.domainSuffix ? `https://${slug}${ingress.domainSuffix}` : null
    }
    return ingress.pathBaseUrl ? `${ingress.pathBaseUrl.replace(/\/$/, '')}/agents/${slug}` : null
}

/**
 * `<SessionGate>` — blocks rendering until `/api/auth/me` resolves
 * (or errors). Mount it once inside the AppShell so child pages can
 * assume the session info is loaded and don't each need their own
 * "Resolving project…" placeholder.
 */
export function SessionGate({ children }: { children: React.ReactNode }): React.ReactElement {
    const { loading, error, info } = useSession()
    if (loading) {
        return (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading session…
            </div>
        )
    }
    if (error) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-destructive-foreground">
                <p>Couldn't reach the session endpoint: {error.message}</p>
                <ServerAnchor href="/api/auth/login">Try logging in again</ServerAnchor>
            </div>
        )
    }
    if (!info || !info.authenticated) {
        return <UnauthedScreen />
    }
    if (info.teamId == null) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-destructive-foreground">
                <p>Your account has no current project. Open PostHog and pick a project, then reload.</p>
                <ServerAnchor href="/api/auth/logout">Sign out</ServerAnchor>
            </div>
        )
    }
    return <>{children}</>
}

/**
 * Full-shell sign-in surface. Renders when the visitor has no session
 * — they see a centered PostHog mark + a single "Sign in with PostHog"
 * action that kicks off the OAuth flow via `/api/auth/login`, preserving
 * the current URL so post-login they land back where they started.
 */
export function UnauthedScreen(): React.ReactElement {
    const loginHref = useLoginHref()
    // The browser navigates away on click, but the OAuth redirect can take a
    // few hundred ms — flip to a spinner so the click feels responsive and
    // the user doesn't double-click thinking nothing happened.
    const [signingIn, setSigningIn] = useState(false)
    return (
        <div className="flex h-full w-full items-center justify-center px-6">
            <div className="flex w-full max-w-sm flex-col items-center gap-6 text-center">
                <PostHogMark className="h-12 w-12 text-foreground" />
                <div className="flex flex-col gap-1">
                    <h1 className="text-lg font-semibold text-foreground">PostHog agent console</h1>
                    <p className="text-sm text-muted-foreground">Sign in to view your agents, sessions, and tools.</p>
                </div>
                {/* eslint-disable-next-line react/forbid-elements */}
                <a
                    href={loginHref}
                    onClick={() => setSigningIn(true)}
                    aria-disabled={signingIn}
                    aria-busy={signingIn}
                    className={
                        signingIn
                            ? 'pointer-events-none inline-flex h-9 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground opacity-80'
                            : 'inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90'
                    }
                >
                    {signingIn ? (
                        <>
                            <Loader2Icon className="h-3.5 w-3.5 animate-spin" aria-hidden />
                            Redirecting…
                        </>
                    ) : (
                        'Sign in with PostHog'
                    )}
                </a>
            </div>
        </div>
    )
}

/**
 * Build the `/api/auth/login` URL with a `returnTo` that reflects the
 * current path + search. After the OAuth round-trip the user lands
 * back on whatever they were trying to reach instead of `/`.
 */
function useLoginHref(): string {
    const pathname = usePathname() ?? '/'
    const searchParams = useSearchParams()
    const search = searchParams?.toString()
    const returnTo = search ? `${pathname}?${search}` : pathname
    return `/api/auth/login?returnTo=${encodeURIComponent(returnTo)}`
}

/**
 * Anchor for `/api/auth/*` routes — these must trigger a real HTTP
 * request (server-side cookie reads, redirects), not Next.js's
 * client-side navigation. Plain `<a>` is correct here; the linter
 * rule that nudges toward `<Link>` doesn't know that.
 */
function ServerAnchor({ href, children }: { href: string; children: React.ReactNode }): React.ReactElement {
    return (
        // eslint-disable-next-line react/forbid-elements
        <a href={href} className="underline">
            {children}
        </a>
    )
}
