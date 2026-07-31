import { useState } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'

// NOTE: intentionally uses local component state rather than a kea logic. The form only collects a
// region + scope selection and builds an authorize URL to redirect to — there is no business logic
// or shared state to host in a logic, and a logic here would add a generated logicType file for no
// behavioural gain. If this grows (async validation, listing reachable teams), promote it to a logic.

type PosthogConnectRegion = 'US' | 'EU'

const REGION_OPTIONS: { value: PosthogConnectRegion; label: string }[] = [
    { value: 'US', label: 'United States (US)' },
    { value: 'EU', label: 'European Union (EU)' },
]

// The `scopes` value maps to what the backend authorize endpoint accepts: the `read_only` / `full`
// presets it expands server-side, or an explicit comma list. A connection can proxy any request its
// granted scopes allow, so these decide how much the connection can do in the target project.
const SCOPE_OPTIONS: { value: string; label: string }[] = [
    { value: 'task:read,task:write', label: 'Tasks only (read and write)' },
    { value: 'read_only', label: 'Read-only (everything)' },
    { value: 'full', label: 'Full access' },
]

export function PosthogConnect({ next }: { next?: string }): JSX.Element {
    const [region, setRegion] = useState<PosthogConnectRegion>('EU')
    const [scopes, setScopes] = useState<string>('task:read,task:write')

    return (
        <div className="deprecated-space-y-2 max-w-prose">
            <p>
                Connect another PostHog project to act in it through its API, for example to dispatch tasks that must run
                there. The project can be in another region (to reach data only accessible from that region) or in your
                own. You'll sign in to that PostHog and approve the access below.
            </p>
            <div className="flex flex-col gap-1">
                <label className="font-semibold">PostHog region</label>
                <LemonSelect<PosthogConnectRegion>
                    value={region}
                    onChange={(value) => setRegion(value ?? 'EU')}
                    options={REGION_OPTIONS}
                />
            </div>
            <div className="flex flex-col gap-1">
                <label className="font-semibold">Access to grant</label>
                <LemonSelect value={scopes} onChange={(value) => setScopes(value ?? 'task:read,task:write')} options={SCOPE_OPTIONS} />
            </div>
            <LemonButton
                type="primary"
                to={api.integrations.authorizeUrl({ kind: 'posthog', region, scopes, next })}
                disableClientSideRouting
            >
                Connect {region}
            </LemonButton>
        </div>
    )
}
