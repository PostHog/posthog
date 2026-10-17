import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: VercelConnect,
}

interface Team {
    id: number
    name: string
    already_linked: boolean
}

interface Organization {
    id: string
    name: string
    already_linked: boolean
    teams: Team[]
}

interface SessionInfo {
    next_url: string
    organizations: Organization[]
}

type SessionErrorReason = 'missing_session' | 'not_logged_in' | 'session_invalid' | 'server_error' | 'network_error'

interface SessionError {
    reason: SessionErrorReason
    message: string
    status?: number
    detail?: string
}

const VERCEL_DASHBOARD_URL = 'https://vercel.com/dashboard'

class SessionFetchError extends Error {
    constructor(public sessionError: SessionError) {
        super(sessionError.message)
    }
}

async function readErrorDetail(res: Response): Promise<string | null> {
    try {
        const data = await res.json()
        return typeof data?.detail === 'string' ? data.detail : null
    } catch {
        return null
    }
}

async function toSessionError(res: Response): Promise<SessionError> {
    const detail = await readErrorDetail(res)
    if (res.status === 401 || res.status === 403) {
        return {
            reason: 'not_logged_in',
            status: res.status,
            message: 'Log in to PostHog to continue linking your Vercel account.',
        }
    }
    if (res.status === 400) {
        return {
            reason: 'session_invalid',
            status: res.status,
            message: detail || "This link session expired or isn't valid. Start again from Vercel.",
        }
    }
    return {
        reason: 'server_error',
        status: res.status,
        detail: detail || undefined,
        message: `PostHog couldn't load this link session (error ${res.status}). Try again, or start again from Vercel.`,
    }
}

function startAgainFromVercel(): void {
    // Vercel opens this page in a popup, so closing it returns the user to Vercel.
    window.close()
    if (!window.closed) {
        window.location.href = VERCEL_DASHBOARD_URL
    }
}

export function VercelConnect(): JSX.Element {
    const { searchParams } = useValues(router)
    const sessionKey = searchParams.session

    const [loading, setLoading] = useState(true)
    const [linking, setLinking] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [sessionError, setSessionError] = useState<SessionError | null>(null)
    const [success, setSuccess] = useState(false)
    const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)
    const [selectedOrg, setSelectedOrg] = useState<string | null>(null)
    const [envMapping, setEnvMapping] = useState<{
        production: number | null
        preview: number | null
        development: number | null
    }>({
        production: null,
        preview: null,
        development: null,
    })
    const [linkedOrgName, setLinkedOrgName] = useState<string>('')

    useEffect(() => {
        const failSession = (failure: SessionError): void => {
            posthog.capture('vercel link page failed', {
                stage: 'session',
                reason: failure.reason,
                status: failure.status,
            })
            setSessionError(failure)
            setLoading(false)
        }

        if (!sessionKey) {
            failSession({
                reason: 'missing_session',
                message: 'This link has no session. Start again from Vercel.',
            })
            return
        }

        fetch(`/api/vercel/connect/session?session=${encodeURIComponent(sessionKey)}`)
            .then(async (res) => {
                if (!res.ok) {
                    throw new SessionFetchError(await toSessionError(res))
                }
                return res.json()
            })
            .then((data: SessionInfo) => {
                setSessionInfo(data)
                const available = data.organizations.filter((o) => !o.already_linked)
                if (available.length === 1) {
                    setSelectedOrg(available[0].id)
                }
                posthog.capture('vercel link page loaded', {
                    organization_count: data.organizations.length,
                    available_organization_count: available.length,
                })
                setLoading(false)
            })
            .catch((err) => {
                failSession(
                    err instanceof SessionFetchError
                        ? err.sessionError
                        : {
                              reason: 'network_error',
                              message: "PostHog couldn't load this link session. Check your connection and try again.",
                          }
                )
            })
    }, [sessionKey])

    useEffect(() => {
        if (selectedOrg && sessionInfo) {
            const org = sessionInfo.organizations.find((o) => o.id === selectedOrg)
            const teams = org?.teams.filter((t) => !t.already_linked) || []
            if (teams.length === 1) {
                const id = teams[0].id
                setEnvMapping({ production: id, preview: id, development: id })
            } else {
                setEnvMapping({ production: null, preview: null, development: null })
            }
        }
    }, [selectedOrg, sessionInfo])

    const handleLink = (): void => {
        if (!selectedOrg || !sessionKey) {
            return
        }

        setLinking(true)
        setError(null)

        fetch('/api/vercel/connect/complete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('posthog_csrftoken') || '',
            },
            body: JSON.stringify({
                session: sessionKey,
                organization_id: selectedOrg,
                environment_mapping: {
                    production: envMapping.production,
                    preview: envMapping.preview || envMapping.production,
                    development: envMapping.development || envMapping.production,
                },
            }),
        })
            .then((res) => {
                if (!res.ok) {
                    return res.json().then((data) => {
                        posthog.capture('vercel link page failed', { stage: 'complete', status: res.status })
                        throw new Error(data.detail || data.attr?.session || 'Failed to link')
                    })
                }
                return res.json()
            })
            .then((data) => {
                posthog.capture('vercel link succeeded')
                setLinkedOrgName(data.organization_name)
                setSuccess(true)
                setLinking(false)

                const returnUrl = data.next_url
                if (returnUrl) {
                    window.location.href = returnUrl
                }
            })
            .catch((err) => {
                setError(err.message || 'Failed to link organization')
                setLinking(false)
            })
    }

    const redirectUrl = sessionInfo?.next_url

    if (loading) {
        return (
            <BridgePage view="vercel-connect">
                <div className="text-center">
                    <Spinner className="text-4xl" />
                    <p className="mt-4">Loading...</p>
                </div>
            </BridgePage>
        )
    }

    if (success) {
        return (
            <BridgePage view="vercel-connect">
                <h2 className="text-center">Account linked</h2>
                <p className="text-center mb-6">
                    Your PostHog organization <strong>{linkedOrgName}</strong> is now connected to Vercel.
                </p>
                {redirectUrl ? (
                    <LemonButton
                        fullWidth
                        type="primary"
                        center
                        onClick={() => {
                            window.location.href = redirectUrl
                        }}
                    >
                        Return to Vercel
                    </LemonButton>
                ) : (
                    <LemonButton fullWidth type="primary" center to="/">
                        Go to PostHog
                    </LemonButton>
                )}
            </BridgePage>
        )
    }

    if (sessionError) {
        const loginUrl = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
        const canRetry = sessionError.reason === 'server_error' || sessionError.reason === 'network_error'
        return (
            <BridgePage view="vercel-connect">
                <h2 className="text-center">
                    {sessionError.reason === 'not_logged_in' ? 'Log in to continue' : "Couldn't load your Vercel link"}
                </h2>
                <p className="text-center text-danger mb-6">{sessionError.message}</p>
                {sessionError.detail && <p className="text-center text-muted text-xs mb-6">{sessionError.detail}</p>}
                <div className="flex flex-col gap-2">
                    {sessionError.reason === 'not_logged_in' && (
                        <LemonButton fullWidth type="primary" center to={loginUrl} disableClientSideRouting>
                            Log in
                        </LemonButton>
                    )}
                    {canRetry && (
                        <LemonButton fullWidth type="primary" center onClick={() => window.location.reload()}>
                            Try again
                        </LemonButton>
                    )}
                    <LemonButton
                        fullWidth
                        type={sessionError.reason === 'not_logged_in' || canRetry ? 'secondary' : 'primary'}
                        center
                        onClick={startAgainFromVercel}
                    >
                        Start again from Vercel
                    </LemonButton>
                </div>
            </BridgePage>
        )
    }

    const availableOrgs = sessionInfo?.organizations.filter((o) => !o.already_linked) || []
    const linkedOrgs = sessionInfo?.organizations.filter((o) => o.already_linked) || []
    const selectedOrgData = sessionInfo?.organizations.find((o) => o.id === selectedOrg)
    const availableTeams = selectedOrgData?.teams.filter((t) => !t.already_linked) || []

    return (
        <BridgePage view="vercel-connect">
            <h2 className="text-center">Connect to Vercel</h2>
            <p className="text-center mb-6">Select which PostHog organization to link to your Vercel account.</p>

            {error && <p className="text-danger text-center mb-4">{error}</p>}

            {availableOrgs.length === 0 ? (
                <div className="text-center mb-6">
                    <p className="text-muted">
                        {linkedOrgs.length > 0
                            ? 'All your organizations are already linked to Vercel.'
                            : "You don't have any organizations with admin access."}
                    </p>
                </div>
            ) : (
                <>
                    <div className="mb-6">
                        <LemonSelect
                            fullWidth
                            placeholder="Select an organization"
                            value={selectedOrg}
                            onChange={(value) => setSelectedOrg(value)}
                            options={availableOrgs.map((org) => ({
                                value: org.id,
                                label: org.name,
                            }))}
                        />
                    </div>

                    {selectedOrg && availableTeams.length > 0 && (
                        <div className="mb-6 space-y-3">
                            {(['production', 'preview', 'development'] as const).map((env) => (
                                <div key={env}>
                                    <label className="text-xs font-medium text-muted uppercase mb-1 block">{env}</label>
                                    <LemonSelect
                                        fullWidth
                                        placeholder="Select a project"
                                        value={envMapping[env]}
                                        onChange={(value) => setEnvMapping((prev) => ({ ...prev, [env]: value }))}
                                        options={availableTeams.map((t) => ({
                                            value: t.id,
                                            label: t.name,
                                        }))}
                                    />
                                </div>
                            ))}
                        </div>
                    )}

                    <LemonButton
                        fullWidth
                        type="primary"
                        center
                        disabled={!selectedOrg || !envMapping.production || linking}
                        loading={linking}
                        onClick={handleLink}
                    >
                        Connect organization
                    </LemonButton>
                </>
            )}

            <LemonButton fullWidth type="secondary" center className="mt-2" onClick={() => window.close()}>
                Cancel
            </LemonButton>
        </BridgePage>
    )
}

export default VercelConnect
