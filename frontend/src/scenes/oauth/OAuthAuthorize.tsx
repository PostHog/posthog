import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo, useState } from 'react'

import { IconCheck, IconCheckCircle, IconLock, IconPlus, IconWarning } from '@posthog/icons'

import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { organizationLogic } from 'scenes/organizationLogic'
import ScopeAccessSelector from 'scenes/settings/user/scopes/ScopeAccessSelector'

import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'
import { AvailableFeature } from '~/types'

import { SceneExport } from '../sceneTypes'
import { OAuthAuthorizeLayout } from './OAuthAuthorizeLayout'
import { ScopeAccessLevel, oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export const OAuthAuthorizeError = ({ title, description }: { title: string; description: string }): JSX.Element => {
    return (
        <div className="AuthScene__card flex flex-col items-center gap-4 p-8 text-center">
            <IconWarning className="text-muted-alt text-4xl" />
            <div className="text-xl font-semibold">{title}</div>
            <div className="text-sm text-muted">{description}</div>
        </div>
    )
}

export const OAuthAuthorizeSuccess = ({ appName }: { appName: string }): JSX.Element => {
    return (
        <div className="AuthScene__card flex flex-col items-center gap-4 p-8">
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
        <div className="AuthScene__card flex flex-col items-center gap-4 p-8">
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
        requiredScopeRows,
        adjustableScopeRows,
        allScopesRequired,
        identityScopeDescriptions,
        showReadOnlyBulkAction,
        oauthApplication,
        oauthApplicationLoading,
        appName,
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
        accessControlsApply,
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
        setScopeAccess,
        setAllScopeAccess,
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
            <OAuthAuthorizeLayout>
                <div className="flex items-center justify-center py-12">
                    <Spinner />
                </div>
            </OAuthAuthorizeLayout>
        )
    }

    if (!oauthApplication) {
        return (
            <OAuthAuthorizeLayout>
                <OAuthAuthorizeError
                    title="No application found"
                    description="The application requesting access to your data does not exist."
                />
            </OAuthAuthorizeLayout>
        )
    }

    if (authorizationComplete) {
        return (
            <OAuthAuthorizeLayout>
                <OAuthAuthorizeSuccess appName={appName} />
            </OAuthAuthorizeLayout>
        )
    }

    if (isRedirecting) {
        return (
            <OAuthAuthorizeLayout>
                <OAuthAuthorizeRedirecting appName={appName} redirectUrl={redirectUrl} />
            </OAuthAuthorizeLayout>
        )
    }

    return (
        <OAuthAuthorizeLayout>
            <div className="shrink-0 mb-3">
                <AuthCardTitle
                    title={
                        <>
                            <span>Authorize </span>
                            <span>{appName}</span>
                        </>
                    }
                    sub={`${appName} is requesting access to your data.`}
                    className="mb-2"
                />
                {user && (
                    <div className="flex items-center justify-center gap-1.5 min-w-0 text-sm text-muted">
                        <ProfilePicture user={user} size="sm" className="shrink-0" />
                        <span className="truncate">
                            <span className="font-semibold text-primary">{user.email}</span>
                            {[currentOrganization?.name ?? user.organization?.name, window.location.host]
                                .filter(Boolean)
                                .map((part) => ` · ${part}`)
                                .join('')}
                        </span>
                    </div>
                )}
            </div>

            {/* Nothing in the column grows: the card hugs a short permission list, and only
                stretches to the window height when the list is longer than that. */}
            <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization" className="flex flex-col min-h-0">
                <div className="AuthScene__card flex flex-col min-h-0 overflow-hidden">
                    {/* Everything the person reads and adjusts scrolls in here. The action row
                        below sits outside, so Authorize stays reachable however many
                        permissions the application asks for. */}
                    <div className="flex flex-col min-h-0 overflow-y-auto" data-attr="oauth-permissions-scroll">
                        <div className="flex flex-col gap-4 sm:gap-6 p-4 sm:p-6">
                            {isImpersonated && (
                                <div className="flex items-center gap-2 p-3 bg-danger-highlight border border-danger rounded text-sm">
                                    <IconWarning className="text-warning shrink-0" />
                                    <span>
                                        <strong>You are impersonating someone.</strong> Any OAuth tokens authorized in
                                        this session are short-lived and will be revoked when impersonation ends
                                        {isImpersonationReadOnly
                                            ? ', and write scopes will be downgraded to read-only'
                                            : ''}
                                        .
                                    </span>
                                </div>
                            )}

                            {!oauthApplication.is_verified && (
                                <div className="flex items-center gap-2 p-3 bg-warning-highlight border border-warning rounded text-sm">
                                    <IconWarning className="text-warning shrink-0" />
                                    <span>
                                        <strong>Unverified application.</strong> This application has not been verified
                                        by PostHog. Only continue if you recognize and trust this application.
                                    </span>
                                </div>
                            )}

                            {scopesWereDefaulted && (
                                <LemonBanner type="info">
                                    <strong>No permissions requested.</strong>{' '}
                                    {isMcpResource
                                        ? "This application didn't request specific permissions. Showing all permissions the PostHog MCP server supports."
                                        : "This application didn't request specific permissions, so everything it can access is selected below. Change anything you don't want to grant."}
                                </LemonBanner>
                            )}

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
                        </div>

                        <div className="flex flex-col">
                            {/* Sticky and full-bleed, so the bulk actions stay in reach once the
                                first rows scroll away. z-10 clears the access selectors, whose
                                own parts sit at z-index 2. */}
                            <div className="AuthScene__cardSurface sticky top-0 z-10 flex items-center justify-between gap-2 flex-wrap px-4 sm:px-6 py-2 border-y border-border">
                                <div className="text-sm font-semibold uppercase text-muted">Permissions</div>
                                {adjustableScopeRows.length > 1 && (
                                    <div className="flex items-center gap-1 flex-wrap">
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => setAllScopeAccess('write')}
                                        >
                                            Select all
                                        </LemonButton>
                                        {showReadOnlyBulkAction && (
                                            <LemonButton
                                                size="xsmall"
                                                type="secondary"
                                                onClick={() => setAllScopeAccess('read')}
                                            >
                                                Read-only
                                            </LemonButton>
                                        )}
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => setAllScopeAccess('none')}
                                        >
                                            Deselect all
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-col gap-3 px-4 sm:px-6 py-4">
                                {(identityScopeDescriptions.length > 0 || requiredScopeRows.length > 0) && (
                                    <ul className="space-y-2">
                                        {identityScopeDescriptions.map((description, idx) => (
                                            <li key={idx} className="flex items-center space-x-2">
                                                <IconCheck color="var(--success)" className="shrink-0" />
                                                <span className="font-medium">{description}</span>
                                            </li>
                                        ))}
                                        {requiredScopeRows.map((row) => (
                                            <li key={row.key} className="flex items-center space-x-2">
                                                <IconCheck color="var(--success)" className="shrink-0" />
                                                <span className="font-medium">{row.description}</span>
                                                {!allScopesRequired && (
                                                    <Tooltip title={`${appName} requires this permission`}>
                                                        <LemonTag>Required</LemonTag>
                                                    </Tooltip>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {adjustableScopeRows.length > 0 && (
                                    <div className="flex flex-col">
                                        {adjustableScopeRows.map((row) => (
                                            <ScopeAccessRow
                                                key={row.key}
                                                label={row.label}
                                                info={row.info}
                                                muted={row.value === 'none'}
                                                value={row.value}
                                                onChange={(value) => setScopeAccess(row.key, value as ScopeAccessLevel)}
                                                noneDisabledReason={
                                                    row.minLevel !== 'none'
                                                        ? `${appName} requires at least ${row.minLevel} access`
                                                        : undefined
                                                }
                                                writeDisabledReason={
                                                    row.maxLevel !== 'write' ? `Not requested by ${appName}` : undefined
                                                }
                                                warning={row.warning}
                                            />
                                        ))}
                                    </div>
                                )}
                                {accessControlsApply && (
                                    <LemonBanner type="info" icon={<IconLock className="LemonBanner__icon" />}>
                                        <strong className="block">Access controls still apply.</strong>
                                        {appName} can only do what both your access level and these permissions allow.
                                    </LemonBanner>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="shrink-0 flex flex-col gap-3 px-4 sm:px-6 py-4 border-t border-border">
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

                        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
                            <LemonButton
                                type="tertiary"
                                status="alt"
                                htmlType="button"
                                data-attr="oauth-authorize-cancel"
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
                                data-attr="oauth-authorize-submit"
                                loading={isOauthAuthorizationSubmitting}
                                disabledReason={
                                    isOauthAuthorizationSubmitting
                                        ? 'Authorizing...'
                                        : isCanceling
                                          ? 'Processing...'
                                          : undefined
                                }
                                onClick={() => submitOauthAuthorization()}
                            >
                                Authorize {appName}
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </Form>
        </OAuthAuthorizeLayout>
    )
}

export const scene: SceneExport = {
    component: OAuthAuthorize,
    logic: oauthAuthorizeLogic,
}
