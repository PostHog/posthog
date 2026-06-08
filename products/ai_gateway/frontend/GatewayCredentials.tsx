import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPlus, IconTrash } from '@posthog/icons'
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

// Buttons to attribute a key to this gateway: assign one of your existing
// unassigned keys, or create a new one pre-scoped for the gateway.
function AddKeyActions({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { assignableCredentials } = useValues(aiGatewayLogic)
    const { assignCredential } = useActions(aiGatewayLogic)

    return (
        <div className="flex items-center gap-2">
            <LemonMenu
                items={assignableCredentials.map((key) => ({
                    label: key.label,
                    onClick: () => assignCredential({ credentialId: key.id, gatewayId: gateway.id }),
                }))}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    disabledReason={
                        !assignableCredentials.length
                            ? 'You have no unassigned personal API keys with the LLM gateway scope'
                            : undefined
                    }
                >
                    Assign existing key
                </LemonButton>
            </LemonMenu>
            <LemonButton type="secondary" size="small" icon={<IconPlus />} to={CREATE_KEY_URL}>
                Create personal API key
            </LemonButton>
        </div>
    )
}

export function GatewayCredentials({ gateway }: { gateway: GatewayApi }): JSX.Element {
    const { credentialsByGateway, credentialsByGatewayLoading } = useValues(aiGatewayLogic)
    const { unassignCredential } = useActions(aiGatewayLogic)

    const credentials = credentialsByGateway[gateway.id]

    if (!credentials) {
        return (
            <div className="px-4 py-2">
                <Spinner /> Loading credentials…
            </div>
        )
    }

    const removeButton = (credentialType: CredentialType, credentialId: string): JSX.Element => (
        <LemonButton
            size="small"
            status="danger"
            icon={<IconTrash />}
            tooltip="Remove from gateway (the key stays, just stops attributing here)"
            onClick={() => unassignCredential({ credentialType, credentialId, gatewayId: gateway.id })}
        />
    )

    if (!credentials.personal_api_keys.length && !credentials.oauth_applications.length) {
        return (
            <div className="flex items-center gap-3 px-4 py-2">
                <span className="text-secondary">No keys attribute usage to this gateway yet.</span>
                <AddKeyActions gateway={gateway} />
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
                    {removeButton('personal_api_key', key.id)}
                </div>
            ))}
            {credentials.oauth_applications.map((app) => (
                <div key={app.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <span>{app.name}</span>
                        <span className="text-secondary">OAuth app · {app.client_id}</span>
                    </div>
                    {removeButton('oauth_application', app.id)}
                </div>
            ))}
            {credentialsByGatewayLoading && <Spinner />}
            <div className="pt-1">
                <AddKeyActions gateway={gateway} />
            </div>
        </div>
    )
}
