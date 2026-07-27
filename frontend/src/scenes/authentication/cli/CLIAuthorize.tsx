import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
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
        <BridgePage view="login">
            {isSuccess ? (
                <div className="text-center space-y-4">
                    <h2>CLI Authorization Complete</h2>
                    <LemonBanner type="success">
                        <div className="space-y-2">
                            <p className="font-semibold">Your CLI has been authorized successfully!</p>
                            <p>You can now close this window and return to your terminal.</p>
                        </div>
                    </LemonBanner>
                    <div className="text-muted text-sm mt-4">
                        <p>
                            A personal API key has been created for your CLI. You can manage your personal API keys in{' '}
                            <Link to={urls.settings('user-api-keys')} className="font-semibold">
                                Settings → Personal API keys
                            </Link>
                        </p>
                    </div>
                </div>
            ) : (
                <div className="space-y-4">
                    <h2>Authorize CLI Access</h2>
                    <p className="text-muted text-sm">
                        The PostHog CLI should have displayed a 9-character code (e.g., ABCD-1234). Enter it below to
                        authorize your CLI.
                    </p>
                    <Form logic={cliAuthorizeLogic} formKey="authorize" enableFormOnSubmit className="space-y-4">
                        <LemonField name="userCode" label="Authorization Code">
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

                        <div className="flex items-center justify-between mt-4 mb-2">
                            <h3 className="mb-0">Scopes</h3>
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
                        <p className="text-muted text-sm mb-2">
                            Permissions granted to the CLI. Pick a preset or fine-tune individual scopes. Only grant
                            what you need.
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
                                        <LemonBanner
                                            type="warning"
                                            action={{ children: 'Reset', onClick: () => resetScopes() }}
                                        >
                                            <b>This key will have full access to all supported endpoints.</b> We
                                            recommend scoping it to only what the CLI needs.
                                        </LemonBanner>
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
                                                            const selected = formScopeRadioValues[key]
                                                            const warningAction =
                                                                selected === 'read' || selected === 'write'
                                                                    ? selected
                                                                    : null
                                                            return (
                                                                <ScopeAccessRow
                                                                    key={key}
                                                                    label={objectName}
                                                                    info={info}
                                                                    value={selected ?? 'none'}
                                                                    onChange={(value) => setScopeRadioValue(key, value)}
                                                                    readDisabledReason={
                                                                        disabledActions?.includes('read')
                                                                            ? 'Does not apply to this resource'
                                                                            : undefined
                                                                    }
                                                                    writeDisabledReason={
                                                                        disabledActions?.includes('write')
                                                                            ? 'Does not apply to this resource'
                                                                            : undefined
                                                                    }
                                                                    warning={
                                                                        warningAction ? warnings?.[warningAction] : null
                                                                    }
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
                            <div className="space-y-2 mt-2">
                                {missingSchemaScopes && (
                                    <LemonBanner type="warning">
                                        <b>Schema management unavailable:</b> The CLI needs both{' '}
                                        <code>event_definition</code> and <code>property_definition</code> permissions
                                        (read or write) to manage schemas.
                                    </LemonBanner>
                                )}
                                {missingErrorTrackingScopes && (
                                    <LemonBanner type="warning">
                                        <b>Error tracking unavailable:</b> The CLI needs <code>error_tracking</code>{' '}
                                        permissions (read or write) to manage error tracking.
                                    </LemonBanner>
                                )}
                                {missingEndpointsScopes && (
                                    <LemonBanner type="warning">
                                        <b>Endpoints unavailable:</b> The CLI needs <code>endpoint</code> permissions
                                        (read or write) to execute endpoints.
                                    </LemonBanner>
                                )}
                                {missingAgentScopes && (
                                    <LemonBanner type="warning">
                                        <b>Agent commands limited:</b> The CLI's <code>api</code> commands need{' '}
                                        <code>user</code>, <code>project</code>, and <code>query</code> permissions
                                        (read or write) to discover data and run queries.
                                    </LemonBanner>
                                )}
                            </div>
                        )}

                        <LemonButton
                            type="primary"
                            status="alt"
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
                </div>
            )}
        </BridgePage>
    )
}
