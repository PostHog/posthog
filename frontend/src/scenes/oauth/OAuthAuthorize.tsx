import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconWarning } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import ScopeAccessSelector from 'scenes/settings/user/scopes/ScopeAccessSelector'

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

export const OAuthAuthorize = (): JSX.Element => {
    const {
        scopeDescriptions,
        oauthApplication,
        oauthApplicationLoading,
        allOrganizations,
        allTeams,
        oauthAuthorization,
        isOauthAuthorizationSubmitting,
        isCanceling,
        redirectDomain,
        requiredAccessLevel,
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
            <OAuthAuthorizeError
                title="No application found"
                description="The application requesting access to your data does not exist."
            />
        )
    }

    return (
        <div className="flex flex-col items-center justify-center h-full">
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
                            accessType={oauthAuthorization.access_type}
                            organizations={allOrganizations}
                            teams={allTeams ?? undefined}
                            requiredAccessLevel={requiredAccessLevel}
                            autoSelectFirst={true}
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

                        {redirectDomain && (
                            <div className="text-xs text-muted">
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
                                          : undefined
                                }
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
