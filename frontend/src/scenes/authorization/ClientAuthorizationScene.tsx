import { LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { ApiScopesList } from 'scenes/settings/user/PersonalAPIKeys'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { clientAuthorizationSceneLogic } from './clientAuthorizationSceneLogic'

export const scene: SceneExport = {
    component: ClientAuthorizationScene,
    logic: clientAuthorizationSceneLogic,
}

export function ClientAuthorizationScene(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { authentication, domain, authenticationLoading, completed } = useValues(clientAuthorizationSceneLogic)
    const { confirmAndRedirect } = useActions(clientAuthorizationSceneLogic)

    if (!authentication && authenticationLoading) {
        return <SpinnerOverlay />
    }

    // TODO: Move to logic
    const scopesObject: Record<string, string> =
        authentication?.scopes?.reduce((acc, scope) => {
            const [resource, method] = scope.split(':')
            acc[resource] = method
            return acc
        }, {}) || {}

    return (
        <div className="h-full flex items-center justify-center">
            <div className="border rounded bg-accent-3000 p-4 w-120">
                {completed ? (
                    <>
                        <h2>Authorization completed!</h2>

                        {authentication?.redirect_url ? (
                            <p>You will shortly be redirected back to the application...</p>
                        ) : (
                            <p>You can now close this window</p>
                        )}
                    </>
                ) : authentication ? (
                    <>
                        <h2>Authorize {authentication.name} </h2>
                        <p>
                            Do you want to give the {authentication.name} access to your PostHog data
                            {domain ? (
                                <>
                                    {' '}
                                    on <b>{domain}</b>
                                </>
                            ) : null}
                            ?
                        </p>
                        <p>
                            The client will have access to data in the project <b>{currentTeam?.name}</b>. If you are in
                            any doubt or did not start an authorization flow from a trusted client then do not authorize
                            and contact PostHog Support
                        </p>

                        <div className="my-2">
                            <h3>Requested scopes</h3>

                            <div className="border rounded overflow-y-auto max-h-100 p-2">
                                <ApiScopesList scopeValues={scopesObject} onlyShowListedValues />
                            </div>
                        </div>

                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary" to={urls.projectHomepage()}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => confirmAndRedirect()}
                                loading={authenticationLoading}
                            >
                                Authorize
                            </LemonButton>
                        </div>
                    </>
                ) : (
                    <>
                        <h2>Something went wrong!</h2>

                        <p>Please restart the authentication flow from your client.</p>
                    </>
                )}
            </div>
        </div>
    )
}
