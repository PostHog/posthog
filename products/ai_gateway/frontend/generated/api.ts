import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    CliAuthorizeApi,
    CliAuthorizedApi,
    CliExchangeApi,
    DevTeamUsageApi,
    DevTokenApi,
    DevTokenRevokeApi,
    DevTokenRevokedApi,
    DevTokenStatusRequestApi,
    DevTokenUsageApi,
    MintedDevTokenApi,
} from './api.schemas'

export const getAiGatewayDevTokensCreateUrl = () => {
    return `/api/ai_gateway/dev_tokens/`
}

/**
 * @summary Create a developer mode token attributed to you
 */
export const aiGatewayDevTokensCreate = async (options?: RequestInit): Promise<MintedDevTokenApi> => {
    return apiMutator<MintedDevTokenApi>(getAiGatewayDevTokensCreateUrl(), {
        ...options,
        method: 'POST',
    })
}

export const getAiGatewayDevTokensCliAuthorizeCreateUrl = () => {
    return `/api/ai_gateway/dev_tokens/cli_authorize/`
}

/**
 * @summary Authorize a CLI login by its PKCE challenge
 */
export const aiGatewayDevTokensCliAuthorizeCreate = async (
    cliAuthorizeApi: CliAuthorizeApi,
    options?: RequestInit
): Promise<CliAuthorizedApi> => {
    return apiMutator<CliAuthorizedApi>(getAiGatewayDevTokensCliAuthorizeCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cliAuthorizeApi),
    })
}

export const getAiGatewayDevTokensCliExchangeCreateUrl = () => {
    return `/api/ai_gateway/dev_tokens/cli_exchange/`
}

/**
 * @summary Exchange a CLI authorization code for a developer mode token
 */
export const aiGatewayDevTokensCliExchangeCreate = async (
    cliExchangeApi: CliExchangeApi,
    options?: RequestInit
): Promise<MintedDevTokenApi> => {
    return apiMutator<MintedDevTokenApi>(getAiGatewayDevTokensCliExchangeCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(cliExchangeApi),
    })
}

export const getAiGatewayDevTokensRevokeCreateUrl = () => {
    return `/api/ai_gateway/dev_tokens/revoke/`
}

/**
 * @summary Revoke one or all of your developer mode tokens
 */
export const aiGatewayDevTokensRevokeCreate = async (
    devTokenRevokeApi?: DevTokenRevokeApi,
    options?: RequestInit
): Promise<DevTokenRevokedApi> => {
    return apiMutator<DevTokenRevokedApi>(getAiGatewayDevTokensRevokeCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(devTokenRevokeApi),
    })
}

export const getAiGatewayDevTokensTeamUsageRetrieveUrl = () => {
    return `/api/ai_gateway/dev_tokens/team_usage/`
}

/**
 * @summary Developer mode minting and spend per user over the last 30 days
 */
export const aiGatewayDevTokensTeamUsageRetrieve = async (options?: RequestInit): Promise<DevTeamUsageApi> => {
    return apiMutator<DevTeamUsageApi>(getAiGatewayDevTokensTeamUsageRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}

export const getAiGatewayDevTokensTokenStatusCreateUrl = () => {
    return `/api/ai_gateway/dev_tokens/token_status/`
}

/**
 * @summary Look up a developer mode token's status and budget left by its bearer
 */
export const aiGatewayDevTokensTokenStatusCreate = async (
    devTokenStatusRequestApi: DevTokenStatusRequestApi,
    options?: RequestInit
): Promise<DevTokenApi> => {
    return apiMutator<DevTokenApi>(getAiGatewayDevTokensTokenStatusCreateUrl(), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(devTokenStatusRequestApi),
    })
}

export const getAiGatewayDevTokensUsageRetrieveUrl = () => {
    return `/api/ai_gateway/dev_tokens/usage/`
}

/**
 * @summary List your live developer mode tokens and today's usage
 */
export const aiGatewayDevTokensUsageRetrieve = async (options?: RequestInit): Promise<DevTokenUsageApi> => {
    return apiMutator<DevTokenUsageApi>(getAiGatewayDevTokensUsageRetrieveUrl(), {
        ...options,
        method: 'GET',
    })
}
