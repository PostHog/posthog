import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import type { ScopeAccessLevel } from 'lib/scopes'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CLI_SCOPE_PRESETS, cliAuthorizeLogic } from './cliAuthorizeLogic'

export const scene: SceneExport = {
    component: CLIAuthorize,
    logic: cliAuthorizeLogic,
}

export function CLIAuthorize(): JSX.Element {
    const {
        authorize,
        isSuccess,
        organizations,
        projects,
        projectsLoading,
        isAuthorizeSubmitting,
        formScopeRadioValues,
        filteredScopes,
        searchTerm,
        scopePreset,
        allAccessSelected,
        missingSchemaScopes,
        missingErrorTrackingScopes,
        missingEndpointsScopes,
        missingAgentScopes,
    } = useValues(cliAuthorizeLogic)
    const { setAuthorizeValue, setScopeRadioValue, setSearchTerm, setScopePreset, resetScopes } =
        useActions(cliAuthorizeLogic)

    return (
        <AuthScene notes={isSuccess ? AUTH_NOTES.cliAuthorize.authorized : AUTH_NOTES.cliAuthorize.authorize}>
            <AuthSceneCard>
                {isSuccess ? (
                    <>
                        <AuthCardTitle title="CLI authorized" sub="Back to the terminal you go." />
                        <AuthBanner variant="success">
                            <p className="m-0 font-semibold">Your CLI has been authorized successfully!</p>
                            <p className="m-0">You can now close this window and return to your terminal.</p>
                        </AuthBanner>
                        <p className="mt-4 mb-0 text-sm text-secondary text-center">
                            <span>A personal API key was created for your CLI. Manage it in</span>{' '}
                            <Link
                                to={urls.settings('user-api-keys')}
                                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                            >
                                Settings → Personal API keys
                            </Link>
                        </p>
                    </>
                ) : (
                    <>
                        <AuthCardTitle
                            title="Authorize CLI access"
                            sub="Type the code your terminal showed you, like ABCD-1234."
                        />
                        <Form
                            logic={cliAuthorizeLogic}
                            formKey="authorize"
                            enableFormOnSubmit
                            className="flex flex-col gap-4"
                        >
                            <LemonField name="userCode" label="Authorization code">
                                <LemonInput
                                    className="ph-ignore-input font-mono text-lg tracking-wider"
                                    autoFocus
                                    data-attr="cli-auth-code"
                                    placeholder="ABCD-1234"
                                    maxLength={9}
                                    value={authorize.userCode}
                                    onChange={(value) => setAuthorizeValue('userCode', value.toUpperCase())}
                                    autoComplete="off"
                                    autoCorrect="off"
                                    autoCapitalize="characters"
                                    spellCheck={false}
                                />
                            </LemonField>
                            <LemonField name="organizationId" label="Organization">
                                <LemonSelect
                                    data-attr="cli-organization-select"
                                    placeholder="Select an organization"
                                    value={authorize.organizationId}
                                    onChange={(value) => setAuthorizeValue('organizationId', value)}
                                    options={organizations.map((organization) => ({
                                        label: organization.name,
                                        value: organization.id,
                                    }))}
                                />
                            </LemonField>
                            <LemonField name="projectId" label="Project">
                                <LemonSelect
                                    data-attr="cli-project-select"
                                    placeholder="Select a project"
                                    value={authorize.projectId}
                                    onChange={(value) => setAuthorizeValue('projectId', value)}
                                    disabled={!authorize.organizationId}
                                    options={projects.map((project: { id: number; name: string }) => ({
                                        label: project.name,
                                        value: project.id,
                                    }))}
                                    loading={projectsLoading}
                                />
                            </LemonField>

                            <div className="flex items-center justify-between mt-2">
                                <span className="font-semibold">Scopes</span>
                                <LemonSelect
                                    data-attr="cli-scope-preset"
                                    size="small"
                                    placeholder="Custom selection"
                                    value={scopePreset}
                                    onChange={(value) => setScopePreset(value)}
                                    options={CLI_SCOPE_PRESETS.map((preset) => ({
                                        label: preset.label,
                                        value: preset.value,
                                    }))}
                                    dropdownMatchSelectWidth={false}
                                    dropdownPlacement="bottom-end"
                                />
                            </div>
                            <p className="-mt-2 mb-0 text-sm text-secondary">
                                Pick a preset or fine-tune individual scopes.
                            </p>

                            <LemonField name="scopes">
                                {({ error }) => (
                                    <>
                                        {error && (
                                            <div className="text-danger flex items-center gap-1 text-sm mb-2">
                                                <IconErrorOutline className="text-xl" /> {error}
                                            </div>
                                        )}

                                        {allAccessSelected ? (
                                            <AuthBanner variant="warning">
                                                <p className="m-0">
                                                    <b>This key will have full access to all supported endpoints.</b>{' '}
                                                    <span>We recommend scoping it to only what the CLI needs.</span>
                                                </p>
                                                <Link
                                                    onClick={() => resetScopes()}
                                                    data-attr="cli-authorize-reset-scopes"
                                                    className="inline-block mt-1 font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                                                >
                                                    Reset scopes
                                                </Link>
                                            </AuthBanner>
                                        ) : (
                                            <>
                                                <LemonInput
                                                    type="search"
                                                    placeholder="Search scopes..."
                                                    value={searchTerm}
                                                    onChange={setSearchTerm}
                                                    className="mb-2"
                                                    size="small"
                                                    fullWidth
                                                />
                                                <div className="max-h-64 overflow-y-auto pr-1">
                                                    {filteredScopes.length === 0 ? (
                                                        <div className="text-muted text-sm py-2">
                                                            No scopes match "{searchTerm}"
                                                        </div>
                                                    ) : (
                                                        filteredScopes.map(
                                                            ({ key, objectName, disabledActions, warnings, info }) => {
                                                                const value = (formScopeRadioValues[key] ??
                                                                    'none') as ScopeAccessLevel
                                                                const disabledReason = (
                                                                    action: 'read' | 'write'
                                                                ): string | undefined =>
                                                                    disabledActions?.includes(action)
                                                                        ? 'Does not apply to this resource'
                                                                        : undefined
                                                                return (
                                                                    <ScopeAccessRow
                                                                        key={key}
                                                                        row={{
                                                                            key,
                                                                            label: objectName,
                                                                            info,
                                                                            value,
                                                                            warning:
                                                                                value === 'none'
                                                                                    ? undefined
                                                                                    : warnings?.[value],
                                                                            disabledReasons: {
                                                                                read: disabledReason('read'),
                                                                                write: disabledReason('write'),
                                                                            },
                                                                        }}
                                                                        onChange={setScopeRadioValue}
                                                                    />
                                                                )
                                                            }
                                                        )
                                                    )}
                                                </div>
                                            </>
                                        )}
                                    </>
                                )}
                            </LemonField>

                            {(missingSchemaScopes ||
                                missingErrorTrackingScopes ||
                                missingEndpointsScopes ||
                                missingAgentScopes) && (
                                <div className="flex flex-col gap-2">
                                    {missingSchemaScopes && (
                                        <AuthBanner variant="warning">
                                            <b>Schema management unavailable:</b> The CLI needs both{' '}
                                            <code>event_definition</code> and <code>property_definition</code>{' '}
                                            permissions (read or write) to manage schemas.
                                        </AuthBanner>
                                    )}
                                    {missingErrorTrackingScopes && (
                                        <AuthBanner variant="warning">
                                            <b>Error tracking unavailable:</b> The CLI needs <code>error_tracking</code>{' '}
                                            permissions (read or write) to manage error tracking.
                                        </AuthBanner>
                                    )}
                                    {missingEndpointsScopes && (
                                        <AuthBanner variant="warning">
                                            <b>Endpoints unavailable:</b> The CLI needs <code>endpoint</code>{' '}
                                            permissions (read or write) to execute endpoints.
                                        </AuthBanner>
                                    )}
                                    {missingAgentScopes && (
                                        <AuthBanner variant="warning">
                                            <b>Agent commands limited:</b> The CLI's <code>api</code> commands need{' '}
                                            <code>user</code>, <code>project</code>, and <code>query</code> permissions
                                            (read or write) to discover data and run queries.
                                        </AuthBanner>
                                    )}
                                </div>
                            )}

                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                data-attr="cli-authorize-submit"
                                fullWidth
                                center
                                loading={isAuthorizeSubmitting}
                                size="large"
                                icon={<IconCode />}
                            >
                                Authorize CLI
                            </LemonButton>
                        </Form>
                    </>
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}
