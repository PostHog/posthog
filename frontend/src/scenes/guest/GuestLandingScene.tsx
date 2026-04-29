import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconNotebook } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

import { GuestGrant } from '~/types'

import { guestSceneLogic } from './guestSceneLogic'

function grantUrl(grant: GuestGrant): string {
    const { team_id, resource_id_url } = grant
    return `/project/${team_id}/notebooks/${resource_id_url}`
}

function grantIcon(): JSX.Element {
    return <IconNotebook fontSize="20" />
}

function GrantCard({ grant }: { grant: GuestGrant }): JSX.Element {
    const label = grant.resource_name || `${grant.resource} ${grant.resource_id_url}`
    return (
        <LemonButton
            type="secondary"
            to={grantUrl(grant)}
            icon={grantIcon()}
            className="w-full justify-start"
            size="medium"
        >
            <span className="flex flex-col items-start text-left">
                <span className="font-medium capitalize">{label}</span>
                <span className="text-xs text-muted capitalize">{grant.resource}</span>
            </span>
        </LemonButton>
    )
}

export function GuestLandingScene(): JSX.Element {
    const { grants, grantsByProject, showsEmptyState, userLoading } = useValues(guestSceneLogic)
    const { searchParams } = useValues(router)
    const { push, replace } = useActions(router)

    // Auto-redirect single-grant guests ONLY when they arrived here via a system deflection
    // (post-login bounce or deep link to a forbidden scene), signalled by `?from=login`.
    // Header "Shared with you" navigates without the flag so the user always lands on the list.
    // The flag is one-shot: we strip it before pushing so a manual refresh of the destination
    // resource doesn't loop back through this auto-redirect.
    const fromLogin = searchParams.from === 'login'
    useEffect(() => {
        if (!fromLogin || grants.length !== 1) {
            return
        }
        replace(window.location.pathname)
        push(grantUrl(grants[0]))
    }, [fromLogin, grants, push, replace])

    if (showsEmptyState) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 p-8 mx-auto max-w-2xl">
                <h1 className="text-2xl font-bold">Your shared content</h1>
                <p className="text-muted">No shared content is available to you at this time.</p>
            </div>
        )
    }

    if (userLoading || grants.length === 0) {
        // Either the user payload is still loading (avoid the "no shared content" flash),
        // or grants aren't populated yet for an authenticated user.
        return <></>
    }

    if (fromLogin && grants.length === 1) {
        // Auto-redirect in progress (see useEffect) — avoid a flash of the single-card list
        // before the navigation lands.
        return <></>
    }

    return (
        <div className="flex flex-col gap-6 p-8 max-w-2xl mx-auto">
            <div>
                <h1 className="text-2xl font-bold">Your shared content</h1>
                <p className="text-muted">Pick one of the resources below to view.</p>
            </div>
            {Object.entries(grantsByProject).map(([teamId, projectGrants]) => {
                const projectName = projectGrants[0]?.team_name || `Project ${teamId}`
                return (
                    <div key={teamId} className="flex flex-col gap-2">
                        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">{projectName}</h2>
                        <div className="flex flex-col gap-2">
                            {projectGrants.map((grant, i) => (
                                <GrantCard key={`${grant.resource}:${grant.resource_id_pk}:${i}`} grant={grant} />
                            ))}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

export const scene: SceneExport = {
    component: GuestLandingScene,
    logic: guestSceneLogic,
}
