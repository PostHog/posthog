import { useMemo, useState } from 'react'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { API_SCOPES, scopesArrayToObject, scopesObjectToArray } from 'lib/scopes'

// NOTE: intentionally uses local component state rather than a kea logic. The form only collects a
// region + scope selection and builds an authorize URL to redirect to — there is no business logic
// or shared state to host in a logic. A logic would also need a generated logicType file. If this
// grows (async validation, listing reachable teams), promote it to a logic.

type PosthogConnectRegion = 'US' | 'EU'

const REGION_OPTIONS: { value: PosthogConnectRegion; label: string }[] = [
    { value: 'US', label: 'United States (US)' },
    { value: 'EU', label: 'European Union (EU)' },
]

// Only offer scopes an OAuth client can actually be granted (mirrors get_oauth_scopes_supported on
// the backend, which excludes privileged/internal/hidden scopes). openid/email are added server-side.
const GRANTABLE_SCOPES = API_SCOPES.filter((scope) => !scope.unprivilegedExcluded)

const readAllScopes = (): string[] =>
    GRANTABLE_SCOPES.filter((s) => !s.disabledActions?.includes('read')).map((s) => `${s.key}:read`)

const fullAccessScopes = (): string[] =>
    GRANTABLE_SCOPES.map((s) => (s.disabledActions?.includes('write') ? `${s.key}:read` : `${s.key}:write`))

const SCOPE_PRESETS: { value: string; label: string; scopes: () => string[] }[] = [
    { value: 'tasks', label: 'Tasks only (read and write)', scopes: () => ['task:read', 'task:write'] },
    { value: 'read_only', label: 'Read-only (everything)', scopes: readAllScopes },
    { value: 'full', label: 'Full access', scopes: fullAccessScopes },
]

export function PosthogConnect({ next }: { next?: string }): JSX.Element {
    const [region, setRegion] = useState<PosthogConnectRegion>('EU')
    const [scopes, setScopes] = useState<string[]>(['task:read', 'task:write'])
    const [searchTerm, setSearchTerm] = useState<string>('')

    const scopeActions = useMemo(() => scopesArrayToObject(scopes), [scopes])

    const setScopeAction = (key: string, action: string): void => {
        const next = scopesArrayToObject(scopes)
        if (action === 'none') {
            delete next[key]
        } else {
            next[key] = action
        }
        setScopes(scopesObjectToArray(next))
    }

    const filteredScopes = useMemo(() => {
        const term = searchTerm.trim().toLowerCase()
        return term ? GRANTABLE_SCOPES.filter((s) => s.objectName.toLowerCase().includes(term)) : GRANTABLE_SCOPES
    }, [searchTerm])

    return (
        <div className="deprecated-space-y-2 max-w-prose">
            <p>
                Connect another PostHog project to act in it through its API, for example to dispatch tasks that must
                run there. The project can be in another region (to reach data only accessible from that region) or in
                your own. You'll sign in to that PostHog and approve the access below.
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
                <div className="flex items-center justify-between gap-2">
                    <label className="font-semibold">Access to grant</label>
                    <LemonSelect
                        placeholder="Apply a preset"
                        size="small"
                        value={null}
                        onChange={(value) => {
                            const preset = SCOPE_PRESETS.find((p) => p.value === value)
                            if (preset) {
                                setScopes(preset.scopes())
                            }
                        }}
                        options={SCOPE_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
                        dropdownMatchSelectWidth={false}
                    />
                </div>
                <LemonInput
                    type="search"
                    placeholder="Search scopes..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    size="small"
                />
                <div className="max-h-[50vh] overflow-y-auto">
                    {filteredScopes.length === 0 ? (
                        <div className="text-muted text-sm py-2">No scopes match "{searchTerm}"</div>
                    ) : (
                        filteredScopes.map((scope) => (
                            <ScopeAccessRow
                                key={scope.key}
                                label={scope.objectName}
                                info={scope.info}
                                value={scopeActions[scope.key] ?? 'none'}
                                onChange={(value) => setScopeAction(scope.key, value)}
                                readDisabledReason={
                                    scope.disabledActions?.includes('read')
                                        ? 'Does not apply to this resource'
                                        : undefined
                                }
                                writeDisabledReason={
                                    scope.disabledActions?.includes('write')
                                        ? 'Does not apply to this resource'
                                        : undefined
                                }
                            />
                        ))
                    )}
                </div>
            </div>
            <LemonButton
                type="primary"
                to={api.integrations.authorizeUrl({
                    kind: 'posthog',
                    next,
                    extraParams: { region, scopes: scopes.join(',') },
                })}
                disableClientSideRouting
                disabledReason={scopes.length === 0 ? 'Select at least one scope' : undefined}
            >
                Connect {region}
            </LemonButton>
        </div>
    )
}
