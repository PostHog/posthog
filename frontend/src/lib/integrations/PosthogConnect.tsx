import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconLogomark, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { TZLabel } from 'lib/components/TZLabel'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { API_SCOPES, scopeMatchesSearch, scopesArrayToObject, scopesObjectToArray } from 'lib/scopes'
import { userLogic } from 'scenes/userLogic'

import { IntegrationType } from '~/types'

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

function PosthogConnectionRow({ integration }: { integration: IntegrationType }): JSX.Element {
    const { deleteIntegration } = useActions(integrationsLogic)
    const region = (integration.config?.region as string | undefined) || 'Unknown'

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: 'Disconnect this PostHog connection?',
            description: (
                <p>
                    PostHog will no longer be able to act in that project on your behalf. Anything using this connection
                    (for example dispatched tasks) will stop working.
                </p>
            ),
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => deleteIntegration(integration.id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                    <IconLogomark />
                </div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{integration.display_name || 'PostHog'}</span>
                    <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded">
                        {region} region
                    </span>
                </div>
                <div className="mt-0.5 text-xs text-secondary">
                    {integration.created_at ? (
                        <>
                            Connected <TZLabel time={integration.created_at} className="align-baseline" />
                        </>
                    ) : (
                        'Connected'
                    )}
                </div>
            </div>
            <div className="flex shrink-0 items-center">
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={handleDisconnect}
                    tooltip="Disconnect this connection"
                />
            </div>
        </div>
    )
}

function ConnectModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
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

    const filteredScopes = useMemo(
        () => GRANTABLE_SCOPES.filter((s) => scopeMatchesSearch(s, searchTerm)),
        [searchTerm]
    )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Connect a PostHog project"
            description="You'll be sent to the target PostHog to sign in and approve the access below."
            width={560}
            footer={
                <LemonButton
                    type="primary"
                    to={api.integrations.authorizeUrl({
                        kind: 'posthog',
                        next: window.location.pathname,
                        extraParams: { region, scopes: scopes.join(',') },
                    })}
                    disableClientSideRouting
                    disabledReason={scopes.length === 0 ? 'Select at least one scope' : undefined}
                >
                    Connect {region}
                </LemonButton>
            }
        >
            <div className="flex flex-col gap-2 h-[60vh]">
                <div className="flex flex-col gap-1">
                    <label className="font-semibold">PostHog region</label>
                    <LemonSelect<PosthogConnectRegion>
                        value={region}
                        onChange={(value) => setRegion(value ?? 'EU')}
                        options={REGION_OPTIONS}
                    />
                </div>
                <div className="flex flex-col gap-1 flex-1 min-h-0">
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
                    <div className="flex-1 min-h-0 overflow-y-auto">
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
            </div>
        </LemonModal>
    )
}

export function PersonalPosthogConnections(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { user } = useValues(userLogic)
    const [modalOpen, setModalOpen] = useState(false)

    if (integrationsLoading && !integrations) {
        return <LemonSkeleton className="h-10" />
    }

    // A connection acts as the user who created it (the forward endpoint is creator-gated), so only
    // show this user's own connections. `kind` is compared as a string because `posthog` lives in the
    // generated integration types, not the legacy manual IntegrationKind union.
    const connections = (integrations ?? []).filter(
        (i) => (i.kind as string) === 'posthog' && i.created_by?.id === user?.id
    )

    return (
        <div className="deprecated-space-y-2">
            <div className="divide-y rounded border bg-surface-primary">
                {connections.length === 0 ? (
                    <div className="px-4 py-6 text-center">
                        <p className="mb-1">No PostHog projects connected yet</p>
                        <p className="text-muted text-sm mb-0">
                            Connect another PostHog project to act in it through its API, for example to dispatch tasks
                            that must run there.
                        </p>
                    </div>
                ) : (
                    connections.map((integration) => (
                        <PosthogConnectionRow key={integration.id} integration={integration} />
                    ))
                )}
                <div className="p-2">
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={() => setModalOpen(true)}>
                        {connections.length === 0 ? 'Connect a PostHog project' : 'Connect another project'}
                    </LemonButton>
                </div>
            </div>
            <ConnectModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
        </div>
    )
}
