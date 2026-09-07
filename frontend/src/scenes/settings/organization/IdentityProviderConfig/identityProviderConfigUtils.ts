import { humanList } from 'lib/utils/strings'

import { ConfigScopeEnumApi, DomainScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'
import { AvailableFeature, OrganizationDomainType } from '~/types'

export type IdentityProviderConfigStatus = 'configured' | 'partially_configured' | 'not_configured'

export interface IdentityProviderFeatureDefinition {
    name: string
    title: string
    description: string
    availableFeature: AvailableFeature
}

const INCOMPLETE_STATUS_DESCRIPTIONS: Record<
    ConfigScopeEnumApi,
    Record<Exclude<IdentityProviderConfigStatus, 'configured'>, string>
> = {
    [ConfigScopeEnumApi.Saml]: {
        not_configured: 'Add your identity provider details to enable SAML single sign-on.',
        partially_configured: 'Add the missing SAML details to finish the configuration.',
    },
    [ConfigScopeEnumApi.Scim]: {
        not_configured: 'Configure SCIM to start provisioning organization members.',
        partially_configured: 'Finish the SCIM setup to start provisioning organization members.',
    },
    [ConfigScopeEnumApi.Xaa]: {
        not_configured: 'Add your identity provider details to automate API and MCP access.',
        partially_configured: 'Add an identity provider issuer URL to finish the configuration.',
    },
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

export function hasSamlDomainScopeConflict(
    configs: readonly IdentityProviderConfigApi[] | null,
    currentConfigId: string | null,
    domainScope: DomainScopeEnumApi,
    selectedDomainIds: readonly string[],
    verifiedDomainIds: readonly string[]
): boolean {
    if (!configs) {
        return false
    }

    const otherSamlConfigs = configs.filter(
        (config) =>
            config.id !== currentConfigId &&
            (config.config_scope === ConfigScopeEnumApi.Saml || config.config_scope == null) &&
            config.has_saml
    )
    const coveredDomainIds =
        domainScope === DomainScopeEnumApi.All
            ? new Set(verifiedDomainIds)
            : new Set(selectedDomainIds.filter((id) => verifiedDomainIds.includes(id)))

    return otherSamlConfigs.some((config) => {
        const configDomainIds =
            config.domain_scope === DomainScopeEnumApi.All ? verifiedDomainIds : (config.organization_domain_ids ?? [])
        return configDomainIds.some((id) => coveredDomainIds.has(id))
    })
}

export function getIdentityProviderConfigsForScope(
    configs: IdentityProviderConfigApi[],
    configScope: ConfigScopeEnumApi
): IdentityProviderConfigApi[] {
    const scopedConfigs = configs.filter((config) => config.config_scope === configScope)
    return scopedConfigs.length > 0
        ? scopedConfigs
        : configs.filter((config) => config.config_scope == null || config.config_scope === '')
}

export function getIdentityProviderConfigForScope(
    configs: IdentityProviderConfigApi[],
    configScope: ConfigScopeEnumApi
): IdentityProviderConfigApi | undefined {
    return getIdentityProviderConfigsForScope(configs, configScope)[0]
}

export interface IdentityProviderConfigStatusDescription {
    text: string
    emphasizedText?: string
    trailingText?: string
}

export function getIdentityProviderConfigStatusDescription(
    config: IdentityProviderConfigApi | undefined,
    configScope: ConfigScopeEnumApi,
    status: IdentityProviderConfigStatus,
    domains: Pick<OrganizationDomainType, 'domain' | 'id' | 'is_verified'>[]
): IdentityProviderConfigStatusDescription {
    if (status === 'partially_configured' && configScope === ConfigScopeEnumApi.Saml) {
        const missingFields = [
            !config?.saml_acs_url ? 'SAML ACS URL' : null,
            !config?.saml_entity_id ? 'SAML entity ID' : null,
            !config?.saml_x509_cert ? 'SAML X.509 certificate' : null,
        ].filter((field): field is string => field !== null)
        if (missingFields.length > 0) {
            return {
                text: 'Add ',
                emphasizedText: humanList(missingFields),
                trailingText: ' to finish the configuration.',
            }
        }
    }

    if (status !== 'configured') {
        return { text: INCOMPLETE_STATUS_DESCRIPTIONS[configScope][status] }
    }

    const verifiedDomains = domains.filter((domain) => domain.is_verified)
    if (config?.domain_scope === DomainScopeEnumApi.All) {
        const domainNames = verifiedDomains.map((domain) => domain.domain)
        return domainNames.length > 0
            ? {
                  text: 'Enabled for all verified domains: ',
                  emphasizedText: humanList(domainNames),
                  trailingText: '.',
              }
            : { text: 'Configured for all verified domains. Verify a domain to enable it.' }
    }

    const selectedDomainIds = new Set(config?.organization_domain_ids ?? [])
    const domainNames = verifiedDomains
        .filter((domain) => selectedDomainIds.has(domain.id))
        .map((domain) => domain.domain)
    if (domainNames.length > 0) {
        return { text: 'Enabled for ', emphasizedText: humanList(domainNames), trailingText: '.' }
    }
    if (selectedDomainIds.size > 0) {
        return { text: 'Configured for selected domains. Verify a selected domain to enable it.' }
    }
    return { text: 'Configured, but not enabled for any domains.' }
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
