import { ConfigScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'
import { AvailableFeature } from '~/types'

export type IdentityProviderConfigStatus = 'configured' | 'partially_configured' | 'not_configured'

export interface IdentityProviderFeatureDefinition {
    name: string
    title: string
    description: string
    availableFeature: AvailableFeature
}

export const IDENTITY_PROVIDER_FEATURES: Record<ConfigScopeEnumApi, IdentityProviderFeatureDefinition> = {
    [ConfigScopeEnumApi.Saml]: {
        name: 'SAML',
        title: 'SAML single sign-on',
        description: 'Configure SAML authentication for your organization.',
        availableFeature: AvailableFeature.SAML,
    },
    [ConfigScopeEnumApi.Scim]: {
        name: 'SCIM',
        title: 'SCIM provisioning',
        description: 'Let your identity provider manage organization members with SCIM.',
        availableFeature: AvailableFeature.SCIM,
    },
    [ConfigScopeEnumApi.Xaa]: {
        name: 'XAA',
        title: 'XAA authentication',
        description: 'Automate API and MCP access to PostHog with Cross App Access (XAA).',
        availableFeature: AvailableFeature.XAA_AUTHENTICATION,
    },
}

export function isIdentityProviderConfigScope(value: string): value is ConfigScopeEnumApi {
    return Object.values(ConfigScopeEnumApi).includes(value as ConfigScopeEnumApi)
}

export function getIdentityProviderConfigForScope(
    configs: IdentityProviderConfigApi[],
    configScope: ConfigScopeEnumApi
): IdentityProviderConfigApi | undefined {
    return (
        configs.find((config) => config.config_scope === configScope) ??
        configs.find((config) => config.config_scope == null || config.config_scope === '')
    )
}

export function getIdentityProviderConfigStatus(
    config: IdentityProviderConfigApi | undefined,
    configScope: ConfigScopeEnumApi
): IdentityProviderConfigStatus {
    if (!config) {
        return 'not_configured'
    }

    if (configScope === ConfigScopeEnumApi.Saml) {
        if (config.has_saml) {
            return 'configured'
        }
        return config.saml_acs_url || config.saml_entity_id || config.saml_x509_cert
            ? 'partially_configured'
            : 'not_configured'
    }

    if (configScope === ConfigScopeEnumApi.Scim) {
        if (config.has_scim) {
            return 'configured'
        }
        return config.scim_enabled ? 'partially_configured' : 'not_configured'
    }

    if (config.has_id_jag) {
        return 'configured'
    }
    return config.id_jag_jwks_url || config.id_jag_allowed_clients?.length ? 'partially_configured' : 'not_configured'
}
