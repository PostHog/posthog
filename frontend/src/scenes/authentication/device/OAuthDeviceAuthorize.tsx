import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { OAuthScopeList } from 'lib/components/ScopeAccessRow/OAuthScopeList'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'

import { oauthDeviceAuthorizeLogic } from './oauthDeviceAuthorizeLogic'

export const scene: SceneExport = {
    component: OAuthDeviceAuthorize,
    logic: oauthDeviceAuthorizeLogic,
}

export function OAuthDeviceAuthorize(): JSX.Element {
    const {
        userCode,
        deviceGrant,
        deviceGrantLoading,
        organizationId,
        organizations,
        projectId,
        projects,
        projectsLoading,
        projectsError,
        decision,
        decisionLoading,
        error,
        isStepUp,
        identityScopeDescriptions,
        requiredScopeRows,
        adjustableScopeRows,
        scopeGroups,
        allScopesRequired,
        scopeSummary,
        keptScopes,
    } = useValues(oauthDeviceAuthorizeLogic)
    const {
        setUserCode,
        lookUpCode,
        setOrganizationId,
        setProjectId,
        loadProjects,
        approve,
        deny,
        setScopeAccess,
        setScopeGroupAccess,
    } = useActions(oauthDeviceAuthorizeLogic)

    if (decision) {
        const approved = decision === 'authorized'
        return (
            <AuthScene notes={approved ? AUTH_NOTES.oauthDevice.approved : AUTH_NOTES.oauthDevice.denied}>
                <AuthSceneCard>
                    <AuthCardTitle
                        title={approved ? 'Login approved' : 'Login denied'}
                        sub="You can close this window and go back to where you started the login."
                    />
                </AuthSceneCard>
            </AuthScene>
        )
    }

    if (!deviceGrant) {
        return (
            <AuthScene notes={AUTH_NOTES.oauthDevice.enterCode}>
                <AuthSceneCard>
                    <AuthCardTitle title="Approve a login" sub="Type the code your terminal shows, like BCDF-GHJK." />
                    <form
                        className="flex flex-col gap-4"
                        onSubmit={(event) => {
                            event.preventDefault()
                            lookUpCode()
                        }}
                    >
                        <LemonField.Pure label="Code" error={error}>
                            <LemonInput
                                className="ph-ignore-input font-mono text-lg tracking-wider"
                                autoFocus
                                data-attr="oauth-device-code"
                                placeholder="BCDF-GHJK"
                                maxLength={20}
                                value={userCode}
                                onChange={setUserCode}
                                autoComplete="off"
                                autoCorrect="off"
                                autoCapitalize="characters"
                                spellCheck={false}
                            />
                        </LemonField.Pure>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            data-attr="oauth-device-continue"
                            fullWidth
                            center
                            size="large"
                            loading={deviceGrantLoading}
                            disabledReason={userCode.trim() ? undefined : 'Type the code first'}
                        >
                            Continue
                        </LemonButton>
                    </form>
                </AuthSceneCard>
            </AuthScene>
        )
    }

    return (
        <AuthScene notes={AUTH_NOTES.oauthDevice.review}>
            <AuthSceneCard>
                <AuthCardTitle
                    title={
                        isStepUp
                            ? `${deviceGrant.client_name} wants more access`
                            : `${deviceGrant.client_name} wants to access your PostHog account`
                    }
                    sub="Check that this code matches the one your terminal shows."
                />
                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-center gap-2">
                        <span
                            className="ph-no-capture font-mono text-2xl font-semibold tracking-wider"
                            data-attr="oauth-device-user-code"
                        >
                            {deviceGrant.user_code}
                        </span>
                        {deviceGrant.is_verified && <LemonTag type="success">Verified app</LemonTag>}
                    </div>
                    <AuthBanner variant="warning">
                        Only approve a login you started yourself. If someone sent you this code, deny it: approving
                        gives them access to your account.
                    </AuthBanner>
                    <LemonField.Pure label="Organization">
                        <LemonSelect
                            data-attr="oauth-device-organization"
                            placeholder="Select an organization"
                            value={organizationId}
                            onChange={setOrganizationId}
                            options={organizations.map((organization) => ({
                                label: organization.name,
                                value: organization.id,
                            }))}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Project" help="The login only works in this project.">
                        <LemonSelect
                            data-attr="oauth-device-project"
                            placeholder="Select a project"
                            value={projectId}
                            onChange={setProjectId}
                            disabledReason={organizationId ? undefined : 'Select an organization first'}
                            loading={projectsLoading}
                            options={projects.map((project) => ({ label: project.name, value: project.id }))}
                        />
                    </LemonField.Pure>
                    {projectsError && organizationId && (
                        <AuthBanner variant="danger">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span>Couldn't load the projects. {projectsError}</span>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => loadProjects(organizationId)}
                                    loading={projectsLoading}
                                    data-attr="oauth-device-retry-projects"
                                >
                                    Try again
                                </LemonButton>
                            </div>
                        </AuthBanner>
                    )}
                    <LemonCollapse
                        panels={[
                            {
                                key: 'permissions',
                                header: (
                                    <span className="font-semibold" data-attr="oauth-device-scope-summary">
                                        {scopeSummary}
                                    </span>
                                ),
                                content: (
                                    <div className="flex flex-col gap-3">
                                        <OAuthScopeList
                                            appName={deviceGrant.client_name}
                                            identityScopeDescriptions={identityScopeDescriptions}
                                            requiredScopeRows={requiredScopeRows}
                                            adjustableScopeRows={adjustableScopeRows}
                                            scopeGroups={scopeGroups}
                                            allScopesRequired={allScopesRequired}
                                            onChangeRow={setScopeAccess}
                                            onChangeGroup={setScopeGroupAccess}
                                            dataAttrPrefix="oauth-device-scope-group"
                                        />
                                    </div>
                                ),
                            },
                        ]}
                    />
                    {error && <AuthBanner variant="danger">{error}</AuthBanner>}
                    <div className="grid grid-cols-2 gap-2">
                        <LemonButton
                            type="secondary"
                            data-attr="oauth-device-deny"
                            fullWidth
                            center
                            size="large"
                            onClick={deny}
                            disabledReason={decisionLoading ? 'Sending your answer' : undefined}
                        >
                            Deny
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="oauth-device-approve"
                            fullWidth
                            center
                            size="large"
                            onClick={approve}
                            loading={decisionLoading}
                            disabledReason={
                                projectId === null
                                    ? 'Select a project first'
                                    : keptScopes.length === 0
                                      ? 'Give at least one permission first'
                                      : undefined
                            }
                        >
                            Approve
                        </LemonButton>
                    </div>
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}
