import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'

// NOTE: intentionally uses local component state rather than a kea logic. The form only collects a
// region + scope selection and builds an authorize URL to redirect to — there is no business logic
// or shared state to host in a logic, and a logic here would add a generated logicType file for no
// behavioural gain. If this grows (async validation, listing reachable teams), promote it to a logic.

type CrossRegion = 'US' | 'EU'

const REGION_OPTIONS: { value: CrossRegion; label: string }[] = [
    { value: 'US', label: 'United States (US)' },
    { value: 'EU', label: 'European Union (EU)' },
]

// Mirrors POSTHOG_CROSS_REGION_GRANTABLE_SCOPES on the backend. Kept deliberately narrow — a
// cross-region grant is standing access into another cell.
const GRANTABLE_SCOPES: { value: string; label: string }[] = [
    { value: 'task:read', label: 'Read tasks' },
    { value: 'task:write', label: 'Create and manage tasks' },
]

export function PosthogCrossRegionConnect({ next }: { next?: string }): JSX.Element {
    const [region, setRegion] = useState<CrossRegion>('EU')
    const [scopes, setScopes] = useState<string[]>(['task:read', 'task:write'])

    const toggleScope = (scope: string, checked: boolean): void => {
        setScopes((current) =>
            checked ? Array.from(new Set([...current, scope])) : current.filter((s) => s !== scope)
        )
    }

    return (
        <div className="deprecated-space-y-2 max-w-prose">
            <p>
                Connect another PostHog region to dispatch tasks that must run there — for example, querying a
                direct-connect source that's only reachable from that region. You'll be sent to that region to sign in
                and approve the permissions below.
            </p>
            <div className="flex flex-col gap-1">
                <label className="font-semibold">Region to connect</label>
                <LemonSelect<CrossRegion>
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
                Connect {region} region
            </LemonButton>
        </div>
    )
}
