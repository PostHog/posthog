import { useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useEffect, useState } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES, type AuthNotes } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
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

export function VercelConnect(): JSX.Element {
    const { searchParams } = useValues(router)
    const sessionKey = searchParams.session

    const [loading, setLoading] = useState(true)
    const [linking, setLinking] = useState(false)
    const [error, setError] = useState<string | null>(null)
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
        if (!sessionKey) {
            setError('Missing session parameter. Please try again from Vercel.')
            setLoading(false)
            return
        }

        fetch(`/api/vercel/connect/session?session=${encodeURIComponent(sessionKey)}`)
            .then((res) => {
                if (!res.ok) {
                    throw new Error('Session expired or invalid')
                }
                return res.json()
            })
            .then((data: SessionInfo) => {
                setSessionInfo(data)
                const available = data.organizations.filter((o) => !o.already_linked)
                if (available.length === 1) {
                    setSelectedOrg(available[0].id)
                }
                setLoading(false)
            })
            .catch((err) => {
                setError(err.message || 'Failed to load session')
                setLoading(false)
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
                        throw new Error(data.detail || data.attr?.session || 'Failed to link')
                    })
                }
                return res.json()
            })
            .then((data) => {
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
            <VercelCard title="Loading your organizations…">
                <div className="flex justify-center">
                    <Spinner className="text-2xl" />
                </div>
            </VercelCard>
        )
    }

    if (success) {
        return (
            <VercelCard
                title="Account linked"
                notes={AUTH_NOTES.vercelConnect.linked}
                sub={
                    <>
                        <span>Your PostHog organization</span> <strong>{linkedOrgName}</strong>{' '}
                        <span>is now connected to Vercel.</span>
                    </>
                }
            >
                {redirectUrl ? (
                    <LemonButton
                        fullWidth
                        type="primary"
                        center
                        size="large"
                        onClick={() => {
                            window.location.href = redirectUrl
                        }}
                    >
                        Return to Vercel
                    </LemonButton>
                ) : (
                    <LemonButton fullWidth type="primary" center size="large" to="/">
                        Go to PostHog
                    </LemonButton>
                )}
            </VercelCard>
        )
    }

    if (error && !sessionInfo) {
        return (
            <VercelCard title="Something went wrong" notes={AUTH_NOTES.vercelConnect.error}>
                <AuthBanner variant="danger">{error}</AuthBanner>
                <LemonButton fullWidth type="secondary" center size="large" onClick={() => window.close()}>
                    Close
                </LemonButton>
            </VercelCard>
        )
    }

    const availableOrgs = sessionInfo?.organizations.filter((o) => !o.already_linked) || []
    const linkedOrgs = sessionInfo?.organizations.filter((o) => o.already_linked) || []
    const selectedOrgData = sessionInfo?.organizations.find((o) => o.id === selectedOrg)
    const availableTeams = selectedOrgData?.teams.filter((t) => !t.already_linked) || []

    return (
        <VercelCard title="Connect to Vercel" sub="Pick the PostHog organization to link.">
            {error && <AuthBanner variant="danger">{error}</AuthBanner>}
            {availableOrgs.length === 0 ? (
                <AuthBanner variant="note">
                    {linkedOrgs.length > 0
                        ? 'All your organizations are already linked to Vercel.'
                        : "You don't have any organizations with admin access."}
                </AuthBanner>
            ) : (
                <>
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
                    {selectedOrg &&
                        availableTeams.length > 0 &&
                        (['production', 'preview', 'development'] as const).map((env) => (
                            <LemonField.Pure key={env} label={capitalizeFirstLetter(env)}>
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
                            </LemonField.Pure>
                        ))}
                    <LemonButton
                        fullWidth
                        type="primary"
                        center
                        size="large"
                        disabled={!selectedOrg || !envMapping.production || linking}
                        loading={linking}
                        onClick={handleLink}
                    >
                        Connect organization
                    </LemonButton>
                </>
            )}
            <LemonButton fullWidth type="secondary" center size="large" onClick={() => window.close()}>
                Cancel
            </LemonButton>
        </VercelCard>
    )
}

function VercelCard({
    title,
    sub,
    notes = AUTH_NOTES.vercelConnect.pick,
    children,
}: {
    title: string
    sub?: ReactNode
    notes?: AuthNotes
    children: ReactNode
}): JSX.Element {
    return (
        <AuthScene notes={notes}>
            <AuthSceneCard>
                <AuthCardTitle title={title} sub={sub} />
                <div className="flex flex-col gap-3">{children}</div>
            </AuthSceneCard>
        </AuthScene>
    )
}

export default VercelConnect
