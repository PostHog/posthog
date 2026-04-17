import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import type { SceneExport } from 'scenes/sceneTypes'

import { GuestGrant } from '~/types'

import { guestSceneLogic } from './guestSceneLogic'

function grantUrl(grant: GuestGrant): string {
    const { team_id, resource, resource_id } = grant
    if (resource === 'dashboard') {
        return `/project/${team_id}/dashboard/${resource_id}`
    }
    if (resource === 'insight') {
        return `/project/${team_id}/insights/${resource_id}`
    }
    if (resource === 'notebook') {
        return `/project/${team_id}/notebooks/${resource_id}`
    }
    return `/project/${team_id}`
}

function GrantCard({ grant }: { grant: GuestGrant }): JSX.Element {
    return (
        <LemonButton type="secondary" to={grantUrl(grant)} className="w-full justify-start capitalize">
            {grant.resource} #{grant.resource_id}
        </LemonButton>
    )
}

export function GuestLandingScene(): JSX.Element {
    const { grants, hasMultipleGrants, grantsByProject } = useValues(guestSceneLogic)
    const { push } = useActions(router)

    useEffect(() => {
        if (grants.length === 1) {
            push(grantUrl(grants[0]))
        }
    }, [grants, push])

    if (grants.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
                <h1 className="text-2xl font-bold">Your shared content</h1>
                <p className="text-muted">No shared content is available to you at this time.</p>
            </div>
        )
    }

    if (!hasMultipleGrants) {
        // Single grant — redirect in progress via useEffect
        return <></>
    }

    return (
        <div className="flex flex-col gap-6 p-8 max-w-2xl mx-auto">
            <h1 className="text-2xl font-bold">Your shared content</h1>
            {Object.entries(grantsByProject).map(([teamId, projectGrants]) => (
                <div key={teamId} className="flex flex-col gap-2">
                    <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">Project {teamId}</h2>
                    <div className="flex flex-col gap-2">
                        {projectGrants.map((grant, i) => (
                            <GrantCard key={i} grant={grant} />
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: GuestLandingScene,
    logic: guestSceneLogic,
}
