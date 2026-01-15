import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconCheckCircle, IconWarning } from '@posthog/icons'

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
        authorizationComplete,
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

    if (authorizationComplete) {
        return <OAuthAuthorizeSuccess appName={oauthApplication.name} />
    }

    return (
        <div className="min-h-full overflow-y-auto">
            <div className="max-w-2xl mx-auto py-8 px-4 sm:py-12 sm:px-6">
                <div className="text-center mb-4 sm:mb-8">
                    <h2 className="text-xl sm:text-2xl font-semibold">
                        Authorize <strong>{oauthApplication.name}</strong>
                    </h2>
                    <p className="text-muted mt-2 text-sm sm:text-base">
                        {oauthApplication.name} is requesting access to your data.
                    </p>
                </div>

                {!oauthApplication.is_verified && (
                    <div className="flex items-center gap-2 p-3 mb-4 bg-warning-highlight border border-warning rounded text-sm">
                        <IconWarning className="text-warning shrink-0" />
                        <span>
                            <strong>Unverified application.</strong> This application has not been verified by PostHog.
                            Only authorize if you trust the developer.
                        </span>
                    </div>
                )}

                <Form logic={oauthAuthorizeLogic} formKey="oauthAuthorization">
                    <div className="flex flex-col gap-4 sm:gap-6 bg-bg-light border border-border rounded p-4 sm:p-6 shadow">
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
