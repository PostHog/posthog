import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import ScopeAccessSelector from 'scenes/settings/user/scopes/ScopeAccessSelector'

import { SceneExport } from '../sceneTypes'
import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export const OAuthAuthorizeError = ({ title, description }: { title: string; description: string }): JSX.Element => {
    return (
        <div className="flex h-full flex-col items-center justify-center gap-4 py-12">
            <IconWarning className="text-muted-alt text-4xl" />
            <div className="text-xl font-semibold">{title}</div>
            <div className="text-muted text-sm">{description}</div>
        </div>
    )
}

export const OAuthAuthorize = (): JSX.Element => {
    const {
        scopeDescriptions,
        oauthApplication,
        oauthApplicationLoading,
        allOrganizations,
        allTeams,
        oauthAuthorization,
        isOauthAuthorizationSubmitting,
        redirectDomain,
    } = useValues(oauthAuthorizeLogic)
    const { cancel, submitOauthAuthorization } = useActions(oauthAuthorizeLogic)

    if (oauthApplicationLoading) {
        return (
            <div className="flex h-full items-center justify-center py-12">
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

    return (
        <div className="flex h-full flex-col items-center justify-center">
            <div className="mx-auto max-w-2xl px-6 py-12">
                <div className="mb-8 text-center">
                    <h2 className="text-2xl font-semibold">
                        Authorize <strong>{oauthApplication.name}</strong>
                    </h2>
                    <p className="text-muted mt-2">{oauthApplication.name} is requesting access to your data.</p>
                </div>

                <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization">
                    <div className="bg-bg-light border-border flex flex-col gap-6 rounded border p-6 shadow">
                        <ScopeAccessSelector
                            accessType={oauthAuthorization.access_type}
                            organizations={allOrganizations}
                            teams={allTeams ?? undefined}
                        />
                        <div>
                            <div className="text-muted mb-2 text-sm font-semibold uppercase">Requested Permissions</div>
                            <ul className="space-y-2">
                                {scopeDescriptions.map((scopeDescription, idx) => (
                                    <li key={idx} className="text-large flex items-center space-x-2">
                                        <IconCheck color="var(--success)" />
                                        <span className="font-medium">{scopeDescription}</span>
                                    </li>
                                ))}
                                <li className="text-large flex items-center space-x-2">
                                    <IconX color="var(--danger)" />
                                    <span className="font-medium">Replace your dashboards with hedgehog memes</span>
                                </li>
                            </ul>
                        </div>

                        {redirectDomain && (
                            <div className="text-muted text-xs">
                                <p>
                                    Once you authorize, you will be redirected to <strong>{redirectDomain}</strong>
                                </p>
                                <p>
                                    The developer of {oauthApplication.name}'s privacy policy and terms of service apply
                                    to this application
                                </p>
                            </div>
                        )}

                        <div className="flex justify-end space-x-2 pt-4">
                            <LemonButton
                                type="tertiary"
                                status="alt"
                                htmlType="button"
                                loading={isOauthAuthorizationSubmitting}
                                disabledReason={isOauthAuthorizationSubmitting ? 'Processing...' : undefined}
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
                                disabledReason={isOauthAuthorizationSubmitting ? 'Authorizing...' : undefined}
                                onClick={() => submitOauthAuthorization()}
                            >
                                Authorize {oauthApplication?.name}
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
