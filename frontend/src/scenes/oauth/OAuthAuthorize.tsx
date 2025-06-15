import { IconCheck, IconWarning } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import ScopeAccessSelector from 'scenes/settings/user/scopes/ScopeAccessSelector'

import { SceneExport } from '../sceneTypes'
import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export const OAuthAuthorize = (): JSX.Element => {
    const {
        scopeDescriptions,
        oauthApplication,
        oauthApplicationLoading,
        allOrganizations,
        allTeams,
        oauthAuthorization,
        isOauthAuthorizationSubmitting,
    } = useValues(oauthAuthorizeLogic)
    const { cancel, submitOauthAuthorization } = useActions(oauthAuthorizeLogic)

    if (oauthApplicationLoading) {
        return (
            <div className="flex items-center justify-center h-full py-12">
                <Spinner />
            </div>
        )
    }

    if (!oauthApplication) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-4 py-12">
                <IconWarning className="text-muted-alt text-4xl" />
                <div className="text-xl font-semibold">No application found</div>
            </div>
        )
    }

    return (
        <div className="max-w-2xl mx-auto py-12 px-6">
            <div className="text-center mb-8">
                <h2 className="text-2xl font-semibold">
                    Authorize <strong>{oauthApplication.name}</strong>
                </h2>
                <p className="text-muted mt-2">{oauthApplication.name} is requesting access to your data.</p>
            </div>

            <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization">
                <div className="flex flex-col gap-6 bg-bg-light border border-border rounded p-6 shadow">
                    <ScopeAccessSelector
                        accessType={oauthAuthorization.access_type ?? 'all'}
                        organizations={allOrganizations}
                        teams={allTeams ?? undefined}
                    />
                    <div>
                        <div className="text-sm font-semibold uppercase text-muted mb-2">Requested Permissions</div>
                        <ul className="space-y-2">
                            {scopeDescriptions.map((scopeDescription, idx) => (
                                <li key={idx} className="flex items-center space-x-2 text-large">
                                    <IconCheck color="var(--success)" />
                                    <span className="font-medium">{scopeDescription}</span>
                                </li>
                            ))}
                        </ul>
                    </div>

                    <div className="flex justify-end space-x-2 pt-4">
                        <LemonButton
                            type="tertiary"
                            status="alt"
                            htmlType="button"
                            disabledReason={isOauthAuthorizationSubmitting ? 'Authorizing...' : undefined}
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
                            disabledReason={isOauthAuthorizationSubmitting ? 'Authorizing...' : undefined}
                            onClick={() => submitOauthAuthorization()}
                        >
                            Authorize {oauthApplication?.name}
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </div>
    )
}

export const scene: SceneExport = {
    component: OAuthAuthorize,
    logic: oauthAuthorizeLogic,
}
