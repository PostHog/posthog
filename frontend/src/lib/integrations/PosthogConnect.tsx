import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

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

// Mirrors POSTHOG_CONNECT_GRANTABLE_SCOPES on the backend. Kept deliberately narrow — a connection
// to another PostHog project is standing delegated access, so only the task scopes are offered.
const GRANTABLE_SCOPES: { value: string; label: string }[] = [
    { value: 'task:read', label: 'Read tasks' },
    { value: 'task:write', label: 'Create and manage tasks' },
]

export function PosthogConnect({ next }: { next?: string }): JSX.Element {
    const [region, setRegion] = useState<PosthogConnectRegion>('EU')
    const [scopes, setScopes] = useState<string[]>(['task:read', 'task:write'])

    const toggleScope = (scope: string, checked: boolean): void => {
        setScopes((current) =>
            checked ? Array.from(new Set([...current, scope])) : current.filter((s) => s !== scope)
        )
    }

    return (
        <div className="deprecated-space-y-2 max-w-prose">
            <p>
                Connect another PostHog project to dispatch tasks that run in it. The project can be in another region
                (for example, to reach a data source only accessible from that region) or in your own. You'll sign in to
                that PostHog and approve the permissions below.
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
                <label className="font-semibold">Permissions to grant</label>
                {GRANTABLE_SCOPES.map((scope) => (
                    <LemonCheckbox
                        key={scope.value}
                        label={scope.label}
                        checked={scopes.includes(scope.value)}
                        onChange={(checked) => toggleScope(scope.value, checked)}
                    />
                ))}
            </div>
            <LemonButton
                type="primary"
                to={api.integrations.authorizeUrl({ kind: 'posthog', region, scopes: scopes.join(','), next })}
                disableClientSideRouting
                disabledReason={scopes.length === 0 ? 'Select at least one permission' : undefined}
            >
                Connect {region}
            </LemonButton>
        </div>
    )
}
