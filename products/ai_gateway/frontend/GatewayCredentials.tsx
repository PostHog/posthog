import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu, Spinner } from '@posthog/lemon-ui'

import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { aiGatewayLogic, CredentialType } from './aiGatewayLogic'
import { GatewayApi, UserBasicApi } from './generated/api.schemas'

// The generated UserBasicApi isn't structurally assignable to ProfilePicture's
// user prop (its hedgehog_config type differs), so narrow to the fields it reads.
export const profileUser = (
    user: UserBasicApi | null
): { first_name?: string; last_name?: string; email?: string } => ({
    first_name: user?.first_name,
    last_name: user?.last_name,
    email: user?.email,
})

// Deep-link to the personal API key settings, opening the create modal pre-filled
// with the llm_gateway:read scope (the `preset` param is read by personalAPIKeysLogic).
export const CREATE_KEY_URL = combineUrl(urls.settings('user-api-keys'), { preset: 'llm_gateway' }).url

// Lists the personal API keys and OAuth apps that attribute usage to a gateway,
// each with a menu to reassign it to another of the team's gateways. Reads the
// credentials lazily — callers must trigger loadCredentials({ gatewayId }) first.
export function GatewayCredentials({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { gateways, credentialsByGateway, credentialsByGatewayLoading } = useValues(aiGatewayLogic)
    const { moveCredential } = useActions(aiGatewayLogic)

    const credentials = credentialsByGateway[gateway.id]
    const otherGateways = gateways.filter((g) => g.id !== gateway.id)

    if (!credentials) {
        return (
            <div className="px-4 py-2">
                <Spinner /> Loading credentials…
            </div>
        )
    }

    const moveMenu = (credentialType: CredentialType, credentialId: string): JSX.Element => (
        <LemonMenu
            items={otherGateways.map((g) => ({
                label: g.slug,
                onClick: () =>
                    moveCredential({ credentialType, credentialId, fromGatewayId: gateway.id, toGatewayId: g.id }),
            }))}
        >
            <LemonButton
                size="small"
                type="secondary"
                disabledReason={!otherGateways.length ? 'No other gateways' : undefined}
            >
                Move to…
            </LemonButton>
        </LemonMenu>
    )

    if (!credentials.personal_api_keys.length && !credentials.oauth_applications.length) {
        return (
            <div className="flex items-center gap-3 px-4 py-2">
                <span className="text-secondary">No credentials attribute usage to this gateway yet.</span>
                <LemonButton type="secondary" size="small" icon={<IconPlus />} to={CREATE_KEY_URL}>
                    Create personal API key
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1 px-4 py-2">
            {credentials.personal_api_keys.map((key) => (
                <div key={key.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={profileUser(key.user)} size="sm" />
                        <span>{key.label}</span>
                        <span className="text-secondary">personal API key</span>
                    </div>
                    {moveMenu('personal_api_key', key.id)}
                </div>
            ))}
            {credentials.oauth_applications.map((app) => (
                <div key={app.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <span>{app.name}</span>
                        <span className="text-secondary">OAuth app · {app.client_id}</span>
                    </div>
                    {moveMenu('oauth_application', app.id)}
                </div>
            ))}
            {credentialsByGatewayLoading && <Spinner />}
        </div>
    )
}
