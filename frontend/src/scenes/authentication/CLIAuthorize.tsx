import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCode } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { cliAuthorizeLogic } from './cliAuthorizeLogic'

export const scene: SceneExport = {
    component: CLIAuthorize,
    logic: cliAuthorizeLogic,
}

export function CLIAuthorize(): JSX.Element {
    const { authorize, isSuccess, projects, projectsLoading, isAuthorizeSubmitting } = useValues(cliAuthorizeLogic)
    const { setAuthorizeValue } = useActions(cliAuthorizeLogic)

    return (
        <BridgePage
            view="login"
            {...(!isSuccess
                ? {
                      hedgehog: true as const,
                      message: (
                          <>
                              Authorize
                              <br />
                              PostHog CLI
                          </>
                      ),
                  }
                : { hedgehog: false as const })}
        >
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
                        <p>A Personal API Key has been created for your CLI with the following scopes:</p>
                        <ul className="list-disc list-inside mt-2">
                            <li>event_definition:read</li>
                            <li>property_definition:read</li>
                            <li>error_tracking:read</li>
                            <li>error_tracking:write</li>
                        </ul>
                        <p className="mt-2">
                            You can manage your API keys in{' '}
                            <Link to={urls.settings('user-api-keys')} className="font-semibold">
                                Settings → Personal API Keys
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
                        <LemonField name="projectId" label="Project">
                            <LemonSelect
                                data-attr="cli-project-select"
                                placeholder="Select a project"
                                value={authorize.projectId}
                                onChange={(value) => setAuthorizeValue('projectId', value)}
                                options={projects.map((project) => ({
                                    label: project.name,
                                    value: project.id,
                                }))}
                                loading={projectsLoading}
                            />
                        </LemonField>
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
                    <div className="text-muted text-sm text-center">
                        <p>
                            This will create a Personal API Key for the PostHog CLI with read-only access to event and
                            property definitions for the selected project.
                        </p>
                    </div>
                </div>
            )}
        </BridgePage>
    )
}
