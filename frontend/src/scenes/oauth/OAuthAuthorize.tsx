import { decode } from 'he'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo, useState } from 'react'

import { IconCheck, IconCheckCircle, IconPlus, IconWarning } from '@posthog/icons'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { organizationLogic } from 'scenes/organizationLogic'
import ScopeAccessSelector from 'scenes/settings/user/scopes/ScopeAccessSelector'

import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'
import { AvailableFeature } from '~/types'

import { SceneExport } from '../sceneTypes'
import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export const OAuthAuthorizeError = ({ title, description }: { title: string; description: string }): JSX.Element => {
    return (
        <div className="flex flex-col items-center justify-center h-full gap-4 py-12">
            <IconWarning className="text-muted-alt text-4xl" />
            <div className="text-xl font-semibold">{title}</div>
            <div className="text-sm text-muted">{description}</div>
        </div>
    )
}

export const OAuthAuthorizeSuccess = ({ appName }: { appName: string }): JSX.Element => {
    return (
        <div className="flex flex-col items-center justify-center h-full gap-4 py-12">
            <IconCheckCircle className="text-success text-4xl" />
            <div className="text-xl font-semibold">Authorization successful</div>
            <div className="text-sm text-muted text-center">
                <p>{appName} has been authorized.</p>
                <p className="mt-2">You can close this window.</p>
            </div>
        </div>
    )
}

export const OAuthAuthorizeRedirecting = ({
    appName,
    redirectUrl,
}: {
    appName: string
    redirectUrl: string
}): JSX.Element => {
    return (
        <div className="flex flex-col items-center justify-center h-full gap-4 py-12 px-4">
            <Spinner className="text-3xl" />
            <div className="text-xl font-semibold">Redirecting to {appName}…</div>
            <div className="text-sm text-muted text-center max-w-md">
                <p>This usually only takes a moment.</p>
                <p className="mt-2">
                    Not redirected automatically? <Link to={redirectUrl}>Click here</Link>.
                </p>
                <p className="mt-2">
                    If {appName} has already finished authorizing on your end, you can safely close this window.
                </p>
            </div>
        </div>
    )
}

const InlineCreateForm = ({
    label,
    placeholder,
    loading,
    onSubmit,
    onCancel,
}: {
    label: string
    placeholder: string
    loading: boolean
    onSubmit: (name: string) => void
    onCancel: () => void
}): JSX.Element => {
    const [name, setName] = useState('')

    return (
        <div className="flex flex-col gap-2 p-3 border border-border rounded bg-bg-light">
            <LemonLabel>{label}</LemonLabel>
            <div className="flex gap-2">
                <LemonInput
                    autoFocus
                    fullWidth
                    placeholder={placeholder}
                    maxLength={64}
                    value={name}
                    onChange={setName}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && name.trim()) {
                            onSubmit(name.trim())
                        }
                        if (e.key === 'Escape') {
                            onCancel()
                        }
                    }}
                    disabled={loading}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    loading={loading}
                    disabledReason={!name.trim() ? 'Enter a name' : undefined}
                    onClick={() => onSubmit(name.trim())}
                >
                    Create
                </LemonButton>
                <LemonButton type="secondary" size="small" onClick={onCancel} disabled={loading}>
                    Cancel
                </LemonButton>
            </div>
        </div>
    )
}

export const OAuthAuthorize = (): JSX.Element => {
    const {
        scopeRows,
        allScopesRequired,
        identityScopeDescriptions,
        showReadOnlyToggle,
        readOnlyMode,
        oauthApplication,
        oauthApplicationLoading,
        allOrganizations,
        filteredTeams,
        oauthAuthorization,
        isOauthAuthorizationSubmitting,
        isCanceling,
        redirectDomain,
        requiredAccessLevel,
        authorizationComplete,
        isRedirecting,
        redirectUrl,
        scopesWereDefaulted,
        isMcpResource,
        resourceScopesLoading,
        showCreateProject,
        newProjectLoading,
        selectedOrganization,
        user,
    } = useValues(oauthAuthorizeLogic)
    const {
        cancel,
        submitOauthAuthorization,
        createNewProject,
        setShowCreateProject,
        setSelectedOrganization,
        setOauthAuthorizationValue,
        setReadOnlyMode,
        toggleDeniedScope,
    } = useActions(oauthAuthorizeLogic)

    const { isReadOnly: isImpersonationReadOnly, isImpersonated } = useValues(impersonationNoticeLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)

    const handleShowCreateProject = (): void => {
        guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, () => setShowCreateProject(true), {
            currentUsage: currentOrganization?.teams?.length,
        })
    }

    const orgOptions = useMemo(() => {
        const currentOrgId = user?.organization?.id
        const sorted = [...allOrganizations].sort((a, b) => {
            if (a.id === currentOrgId) {
                return -1
            }
            if (b.id === currentOrgId) {
                return 1
            }
            return a.name.localeCompare(b.name)
        })
        return sorted.map((org) => ({
            value: org.id,
            label: org.name,
        }))
    }, [allOrganizations, user?.organization?.id])

    const projectOptions = useMemo(() => {
        if (!filteredTeams) {
            return []
        }
        const currentTeamId = user?.team?.id
        return [...filteredTeams]
            .sort((a, b) => {
                if (a.id === currentTeamId) {
                    return -1
                }
                if (b.id === currentTeamId) {
                    return 1
                }
                return a.name.localeCompare(b.name)
            })
            .map((team) => ({
                value: team.id,
                label: team.name,
            }))
    }, [filteredTeams, user?.team?.id])

    if (oauthApplicationLoading) {
        return (
            <div className="flex items-center justify-center h-full py-12">
                <Spinner />
            </div>
        )
    }

    if (!oauthApplication) {
        return (
            <OAuthAuthorizeError
                title="No application found"
                description="The application requesting access to your data does not exist."
            />
        )
    }

    // The name is HTML-escaped at ingestion (see posthog/api/oauth/client_name.py). Decode it
    // back to plain text so React's own output-escaping renders it correctly instead of showing
    // literal entities like "&amp;".
    const appName = decode(oauthApplication.name)

    if (authorizationComplete) {
        return <OAuthAuthorizeSuccess appName={appName} />
    }

    if (isRedirecting) {
        return <OAuthAuthorizeRedirecting appName={appName} redirectUrl={redirectUrl} />
    }

    return (
        <div className="min-h-full overflow-y-auto">
            <div className="max-w-2xl mx-auto py-8 px-4 sm:py-12 sm:px-6">
                <div className="text-center mb-4 sm:mb-8">
                    {oauthApplication.logo_uri && (
                        <div className="w-16 h-16 mx-auto mb-3 rounded-full border border-border bg-bg-light p-3 flex items-center justify-center">
                            <img
                                src={oauthApplication.logo_uri}
                                alt={`${appName} logo`}
                                className="w-full h-full object-contain"
                                referrerPolicy="no-referrer"
                                onError={(e) => {
                                    // Hide the image container if the logo fails to load
                                    // (e.g. Cross-Origin-Resource-Policy: same-origin)
                                    const container = (e.target as HTMLImageElement).parentElement
                                    if (container) {
                                        container.style.display = 'none'
                                    }
                                }}
                            />
                        </div>
                    )}
                    <h2 className="text-xl sm:text-2xl font-semibold">
                        Authorize <strong>{appName}</strong>
                    </h2>
                    <p className="text-muted mt-2 text-sm sm:text-base">{appName} is requesting access to your data.</p>
                </div>

                {isImpersonated && (
                    <div className="flex items-center gap-2 p-3 mb-4 bg-danger-highlight border border-danger rounded text-sm">
                        <IconWarning className="text-warning shrink-0" />
                        <span>
                            <strong>You are impersonating someone.</strong> Any OAuth tokens authorized in this session
                            are short-lived and will be revoked when impersonation ends
                            {isImpersonationReadOnly ? ', and write scopes will be downgraded to read-only' : ''}.
                        </span>
                    </div>
                )}

                {!oauthApplication.is_verified && (
                    <div className="flex items-center gap-2 p-3 mb-4 bg-warning-highlight border border-warning rounded text-sm">
                        <IconWarning className="text-warning shrink-0" />
                        <span>
                            <strong>Unverified application.</strong> This application has not been verified by PostHog.
                            Only continue if you recognize and trust this application.
                        </span>
                    </div>
                )}

                {scopesWereDefaulted && isMcpResource && (
                    <LemonBanner type="info" className="mb-4">
                        <strong>No permissions requested.</strong> This application didn't request specific permissions.
                        Showing all permissions supported by this resource.
                    </LemonBanner>
                )}

                <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization">
                    <div className="flex flex-col gap-4 sm:gap-6 bg-bg-light border border-border rounded p-4 sm:p-6 shadow">
                        {requiredAccessLevel === 'team' ? (
                            <>
                                <div className="flex flex-col gap-2">
                                    <LemonLabel>Organization</LemonLabel>
                                    <LemonSelect
                                        fullWidth
                                        placeholder="Select organization"
                                        options={orgOptions}
                                        value={selectedOrganization}
                                        onChange={(val) => {
                                            if (val) {
                                                setSelectedOrganization(val)
                                            }
                                        }}
                                    />
                                </div>

                                <div className="flex flex-col gap-2">
                                    <LemonLabel>Project</LemonLabel>
                                    {showCreateProject ? (
                                        <InlineCreateForm
                                            label="New project name"
                                            placeholder="e.g. My App"
                                            loading={newProjectLoading}
                                            onSubmit={createNewProject}
                                            onCancel={() => setShowCreateProject(false)}
                                        />
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            <div className="flex-1 min-w-0">
                                                <LemonSelect
                                                    fullWidth
                                                    placeholder={
                                                        selectedOrganization
                                                            ? 'Select project'
                                                            : 'Select an organization first'
                                                    }
                                                    options={projectOptions}
                                                    value={oauthAuthorization.scoped_teams[0] ?? null}
                                                    onChange={(val) => {
                                                        if (val) {
                                                            setOauthAuthorizationValue('scoped_teams', [val])
                                                        }
                                                    }}
                                                    disabledReason={
                                                        !selectedOrganization
                                                            ? 'Select an organization first'
                                                            : undefined
                                                    }
                                                />
                                            </div>
                                            <LemonButton
                                                className="shrink-0"
                                                type="secondary"
                                                size="small"
                                                icon={<IconPlus />}
                                                disabledReason={
                                                    !selectedOrganization
                                                        ? 'Select an organization first'
                                                        : (projectCreationForbiddenReason ?? undefined)
                                                }
                                                onClick={handleShowCreateProject}
                                            />
                                        </div>
                                    )}
                                </div>
                            </>
                        ) : (
                            <ScopeAccessSelector
                                accessType={oauthAuthorization.access_type}
                                organizations={allOrganizations}
                                teams={filteredTeams ?? undefined}
                                requiredAccessLevel={requiredAccessLevel}
                                autoSelectFirst={true}
                            />
                        )}

                        <div className="flex flex-col gap-3">
                            <div className="flex items-center justify-between gap-2 flex-wrap">
                                <div className="text-sm font-semibold uppercase text-muted">Permissions</div>
                                {showReadOnlyToggle && (
                                    <LemonSegmentedButton
                                        size="small"
                                        value={readOnlyMode ? 'read' : 'full'}
                                        onChange={(value) => setReadOnlyMode(value === 'read')}
                                        options={[
                                            { value: 'full', label: 'All requested' },
                                            { value: 'read', label: 'Read-only' },
                                        ]}
                                    />
                                )}
                            </div>
                            {resourceScopesLoading ? (
                                <div className="flex items-center gap-2 py-2">
                                    <Spinner className="text-muted" />
                                    <span className="text-muted">Loading permissions...</span>
                                </div>
                            ) : (
                                <>
                                    {identityScopeDescriptions.length > 0 && (
                                        <ul className="space-y-2">
                                            {identityScopeDescriptions.map((description, idx) => (
                                                <li key={idx} className="flex items-center space-x-2">
                                                    <IconCheck color="var(--success)" />
                                                    <span className="font-medium">{description}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                    {scopeRows.length > 0 &&
                                        (allScopesRequired ? (
                                            <ul className="space-y-2">
                                                {scopeRows.map((row) => (
                                                    <li key={row.key} className="flex items-center space-x-2">
                                                        <IconCheck color="var(--success)" />
                                                        <span className="font-medium">{row.description}</span>
                                                    </li>
                                                ))}
                                            </ul>
                                        ) : (
                                            <div className="flex flex-col gap-2">
                                                {scopeRows.map((row) => (
                                                    <LemonCheckbox
                                                        key={row.key}
                                                        checked={row.granted}
                                                        onChange={() =>
                                                            row.toggleKey && toggleDeniedScope(row.toggleKey)
                                                        }
                                                        label={row.description}
                                                        disabledReason={
                                                            row.required ? `Required by ${appName}` : undefined
                                                        }
                                                    />
                                                ))}
                                            </div>
                                        ))}
                                </>
                            )}
                        </div>

                        {redirectDomain && (
                            <div className="text-xs text-muted">
                                <p>
                                    Once you authorize, you will be redirected to <strong>{redirectDomain}</strong>
                                </p>
                                <p>
                                    The developer of {appName}'s privacy policy and terms of service apply to this
                                    application
                                </p>
                            </div>
                        )}

                        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-4">
                            <LemonButton
                                type="tertiary"
                                status="alt"
                                htmlType="button"
                                loading={isCanceling}
                                disabledReason={
                                    isCanceling
                                        ? 'Canceling...'
                                        : isOauthAuthorizationSubmitting
                                          ? 'Processing...'
                                          : undefined
                                }
                                onClick={(e) => {
                                    e.preventDefault()
                                    cancel()
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isOauthAuthorizationSubmitting}
                                disabledReason={
                                    isOauthAuthorizationSubmitting
                                        ? 'Authorizing...'
                                        : isCanceling
                                          ? 'Processing...'
                                          : resourceScopesLoading
                                            ? 'Loading permissions...'
                                            : undefined
                                }
                                onClick={() => submitOauthAuthorization()}
                            >
                                Authorize {appName}
                            </LemonButton>
                        </div>
                    </div>
                </Form>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: OAuthAuthorize,
    logic: oauthAuthorizeLogic,
}
