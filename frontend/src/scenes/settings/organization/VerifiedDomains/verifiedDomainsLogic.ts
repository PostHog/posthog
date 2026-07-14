import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { SECURE_URL_REGEX } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { bindModalToUrl } from 'lib/logic/bindModalToUrl'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import {
    domainsCreate,
    domainsDestroy,
    domainsList,
    domainsPartialUpdate,
    domainsScimLogsList,
    domainsVerifyCreate,
    identityProviderConfigsCreate,
    identityProviderConfigsDomainsPartialUpdate,
    identityProviderConfigsList,
    identityProviderConfigsPartialUpdate,
    identityProviderConfigsScimTokenCreate,
} from '~/generated/core/api'
import {
    IdentityProviderConfigApi,
    IdentityProviderConfigDomainsKindEnumApi,
    OrganizationDomainApi,
    PaginatedSCIMRequestLogListApi,
    PatchedIdentityProviderConfigApi,
} from '~/generated/core/api.schemas'
import { AvailableFeature } from '~/types'

import type { verifiedDomainsLogicType } from './verifiedDomainsLogicType'

function currentOrganizationId(): string {
    const organizationId = organizationLogic.values.currentOrganizationId
    if (!organizationId) {
        throw new Error('An organization must be selected to manage identity provider settings.')
    }
    return organizationId
}

export type OrganizationDomainUpdatePayload = Partial<
    Pick<OrganizationDomainApi, 'jit_provisioning_enabled' | 'sso_enforcement'>
> &
    Pick<OrganizationDomainApi, 'id'>

type IdentityProviderConfigFormBase = { id?: string; name: string; domain_ids: string[] }

export type SAMLConfigType = IdentityProviderConfigFormBase &
    Pick<IdentityProviderConfigApi, 'saml_acs_url' | 'saml_entity_id' | 'saml_x509_cert'>
export type SCIMConfigType = IdentityProviderConfigFormBase &
    Pick<IdentityProviderConfigApi, 'scim_enabled'> & { scim_bearer_token?: string | null }
export type IdJagConfigType = IdentityProviderConfigFormBase &
    Pick<IdentityProviderConfigApi, 'id_jag_issuer_url' | 'id_jag_jwks_url' | 'id_jag_allowed_clients'>

const DEFAULT_IDENTITY_PROVIDER_NAMES = {
    saml: 'SAML configuration',
    scim: 'SCIM configuration',
    idJag: 'XAA configuration',
} as const

async function saveIdentityProviderConfig(
    organizationId: string,
    id: string | undefined,
    config: PatchedIdentityProviderConfigApi,
    kind: IdentityProviderConfigDomainsKindEnumApi,
    domainIds: string[]
): Promise<IdentityProviderConfigApi> {
    const savedConfig = id
        ? await identityProviderConfigsPartialUpdate(organizationId, id, config)
        : await identityProviderConfigsCreate(organizationId, config)
    const configWithDomains = await identityProviderConfigsDomainsPartialUpdate(organizationId, savedConfig.id, {
        kind,
        domain_ids: domainIds,
    })
    return { ...configWithDomains, scim_bearer_token: savedConfig.scim_bearer_token }
}

export const isSecureURL = (url: string): boolean => {
    try {
        return new URL(url).protocol === 'https:'
    } catch {
        return false
    }
}

function getSamlConfig(configs: IdentityProviderConfigApi[]): IdentityProviderConfigApi | undefined {
    return configs.find(
        (config) =>
            config.saml_domain_ids.length || config.saml_entity_id || config.saml_acs_url || config.saml_x509_cert
    )
}

function getScimConfig(configs: IdentityProviderConfigApi[]): IdentityProviderConfigApi | undefined {
    return configs.find((config) => config.scim_domain_ids.length || config.scim_enabled)
}

function getIdJagConfig(configs: IdentityProviderConfigApi[]): IdentityProviderConfigApi | undefined {
    return configs.find((config) => config.id_jag_domain_ids.length || config.id_jag_issuer_url)
}

export const verifiedDomainsLogic = kea<verifiedDomainsLogicType>([
    path(['scenes', 'organization', 'verifiedDomainsLogic']),
    actions({
        replaceDomain: (domain: OrganizationDomainApi) => ({ domain }),
        showAddDomainModal: true,
        hideAddDomainModal: true,
        setScimPlaintextToken: (token: string | null) => ({ token }),
        setRegeneratingScimToken: (regenerating: boolean) => ({ regenerating }),
        regenerateScimToken: (configId: string) => ({ configId }),
        setScimLogsModalId: (id: string | null) => ({ id }),
        setScimLogsStatusFilter: (filter: 'all' | 'success' | '4xx' | '5xx') => ({ filter }),
        setScimLogsSearch: (search: string) => ({ search }),
        setScimLogsPage: (page: number) => ({ page }),
        reloadScimLogs: true,
        setVerifyModal: (id: string | null) => ({ id }),
        reloadIdentitySettings: true,
    }),
    reducers({
        verifiedDomains: [
            [] as OrganizationDomainApi[],
            {
                replaceDomain: (state, { domain }) =>
                    [...state.filter(({ id }) => id !== domain.id), domain].sort((a, b) =>
                        a.domain.localeCompare(b.domain)
                    ),
            },
        ],
        addModalShown: [
            false,
            {
                showAddDomainModal: () => true,
                hideAddDomainModal: () => false,
                addVerifiedDomainSuccess: () => false,
            },
        ],
        scimPlaintextToken: [null as string | null, { setScimPlaintextToken: (_, { token }) => token }],
        regeneratingScimToken: [false, { setRegeneratingScimToken: (_, { regenerating }) => regenerating }],
        scimLogsModalId: [null as string | null, { setScimLogsModalId: (_, { id }) => id }],
        scimLogsStatusFilter: [
            'all' as 'all' | 'success' | '4xx' | '5xx',
            { setScimLogsStatusFilter: (_, { filter }) => filter, setScimLogsModalId: () => 'all' },
        ],
        scimLogsSearch: ['', { setScimLogsSearch: (_, { search }) => search, setScimLogsModalId: () => '' }],
        scimLogsPage: [
            1,
            {
                setScimLogsPage: (_, { page }) => page,
                setScimLogsModalId: () => 1,
                setScimLogsStatusFilter: () => 1,
                setScimLogsSearch: () => 1,
            },
        ],
        verifyModal: [null as string | null, { setVerifyModal: (_, { id }) => id }],
    }),
    loaders(({ values, actions }) => ({
        verifiedDomains: [
            [] as OrganizationDomainApi[],
            {
                loadVerifiedDomains: async () => (await domainsList(currentOrganizationId(), { limit: 100 })).results,
                addVerifiedDomain: async (domain: string) => [
                    ...values.verifiedDomains,
                    await domainsCreate(currentOrganizationId(), { domain }),
                ],
                deleteVerifiedDomain: async (id: string) => {
                    await domainsDestroy(currentOrganizationId(), id)
                    return values.verifiedDomains.filter((domain) => domain.id !== id)
                },
            },
        ],
        identityProviderConfigs: [
            [] as IdentityProviderConfigApi[],
            {
                loadIdentityProviderConfigs: async () =>
                    (await identityProviderConfigsList(currentOrganizationId())).results,
            },
        ],
        updatingDomain: [
            false,
            {
                updateDomain: async (payload: OrganizationDomainUpdatePayload) => {
                    const response = await domainsPartialUpdate(currentOrganizationId(), payload.id, {
                        jit_provisioning_enabled: payload.jit_provisioning_enabled,
                        sso_enforcement: payload.sso_enforcement,
                    })
                    lemonToast.success('Domain updated. Changes take effect immediately.')
                    actions.replaceDomain(response)
                    return false
                },
                verifyDomain: async () => {
                    if (!values.verifyModal) {
                        return false
                    }
                    const response = await domainsVerifyCreate(currentOrganizationId(), values.verifyModal)
                    if (response.is_verified) {
                        lemonToast.success('Domain verified successfully.')
                    } else {
                        lemonToast.warning(
                            'We could not verify your domain yet. DNS propagation may take up to 72 hours. Please try again later.'
                        )
                    }
                    actions.replaceDomain(response)
                    actions.setVerifyModal(null)
                    return false
                },
            },
        ],
        scimLogs: [
            null as PaginatedSCIMRequestLogListApi | null,
            {
                setScimLogsModalId: () => null,
                loadScimLogs: async ({ domainId, page }: { domainId: string; page?: number }, breakpoint) => {
                    await breakpoint(300)
                    const statusRange =
                        values.scimLogsStatusFilter === 'success'
                            ? { status_min: 200, status_max: 299 }
                            : values.scimLogsStatusFilter === '4xx'
                              ? { status_min: 400, status_max: 499 }
                              : values.scimLogsStatusFilter === '5xx'
                                ? { status_min: 500 }
                                : {}
                    const response = await domainsScimLogsList(currentOrganizationId(), domainId, {
                        ...statusRange,
                        search: values.scimLogsSearch || undefined,
                        page,
                    })
                    await breakpoint()
                    return response
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        reloadIdentitySettings: () => {
            actions.loadVerifiedDomains()
            actions.loadIdentityProviderConfigs()
        },
        loadIdentityProviderConfigsSuccess: ({ identityProviderConfigs }) => {
            const samlConfig = getSamlConfig(identityProviderConfigs)
            const scimConfig = getScimConfig(identityProviderConfigs)
            const idJagConfig = getIdJagConfig(identityProviderConfigs)
            actions.resetSamlConfig({
                id: samlConfig?.id,
                name: samlConfig?.name || DEFAULT_IDENTITY_PROVIDER_NAMES.saml,
                domain_ids: [...(samlConfig?.saml_domain_ids || [])],
                saml_acs_url: samlConfig?.saml_acs_url || '',
                saml_entity_id: samlConfig?.saml_entity_id || '',
                saml_x509_cert: samlConfig?.saml_x509_cert || '',
            })
            actions.resetScimConfig({
                id: scimConfig?.id,
                name: scimConfig?.name || DEFAULT_IDENTITY_PROVIDER_NAMES.scim,
                domain_ids: [...(scimConfig?.scim_domain_ids || [])],
                scim_enabled: scimConfig?.scim_enabled || false,
            })
            actions.resetIdJagConfig({
                id: idJagConfig?.id,
                name: idJagConfig?.name || DEFAULT_IDENTITY_PROVIDER_NAMES.idJag,
                domain_ids: [...(idJagConfig?.id_jag_domain_ids || [])],
                id_jag_issuer_url: idJagConfig?.id_jag_issuer_url || '',
                id_jag_jwks_url: idJagConfig?.id_jag_jwks_url || '',
                id_jag_allowed_clients: idJagConfig?.id_jag_allowed_clients || [],
            })
        },
        regenerateScimToken: async ({ configId }) => {
            actions.setRegeneratingScimToken(true)
            try {
                const response = await identityProviderConfigsScimTokenCreate(currentOrganizationId(), configId)
                actions.setScimPlaintextToken(response.scim_bearer_token)
                lemonToast.success('SCIM token regenerated.')
            } finally {
                actions.setRegeneratingScimToken(false)
            }
        },
        setScimLogsModalId: ({ id }) => {
            if (id) {
                actions.loadScimLogs({ domainId: id })
            }
        },
        setScimLogsStatusFilter: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId })
            }
        },
        setScimLogsSearch: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId })
            }
        },
        setScimLogsPage: ({ page }) => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId, page })
            }
        },
        reloadScimLogs: () => {
            if (values.scimLogsModalId) {
                actions.loadScimLogs({ domainId: values.scimLogsModalId, page: values.scimLogsPage })
            }
        },
    })),
    selectors({
        domainBeingVerified: [
            (s) => [s.verifiedDomains, s.verifyModal],
            (domains, id): OrganizationDomainApi | null => (id && domains.find((domain) => domain.id === id)) || null,
        ],
        verifiedDomainsList: [
            (s) => [s.verifiedDomains],
            (domains: OrganizationDomainApi[]): OrganizationDomainApi[] =>
                domains.filter(({ is_verified }) => is_verified),
        ],
        unverifiedDomainsList: [
            (s) => [s.verifiedDomains],
            (domains: OrganizationDomainApi[]): OrganizationDomainApi[] =>
                domains.filter(({ is_verified }) => !is_verified),
        ],
        isSSOEnforcementAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasFeature): boolean => hasFeature(AvailableFeature.SSO_ENFORCEMENT),
        ],
        isSAMLAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasFeature): boolean => hasFeature(AvailableFeature.SAML),
        ],
        isSCIMAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasFeature): boolean => hasFeature(AvailableFeature.SCIM),
        ],
        isXAAAuthenticationAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasFeature): boolean => hasFeature(AvailableFeature.XAA_AUTHENTICATION),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadVerifiedDomains()
        actions.loadIdentityProviderConfigs()
    }),
    bindModalToUrl({
        urlKey: 'add-domain',
        openActionKey: 'showAddDomainModal',
        closeActionKey: 'hideAddDomainModal',
        isOpenKey: 'addModalShown',
    }),
    forms(({ actions }) => ({
        samlConfig: {
            defaults: { name: DEFAULT_IDENTITY_PROVIDER_NAMES.saml, domain_ids: [] } as SAMLConfigType,
            errors: (payload) => ({
                domain_ids: payload.domain_ids.length === 0 ? ['Select at least one domain.'] : undefined,
                saml_acs_url:
                    payload.saml_acs_url && !payload.saml_acs_url.match(SECURE_URL_REGEX)
                        ? 'Enter a valid URL, including https://'
                        : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const config = await saveIdentityProviderConfig(
                    currentOrganizationId(),
                    payload.id,
                    {
                        name: payload.name,
                        saml_acs_url: payload.saml_acs_url,
                        saml_entity_id: payload.saml_entity_id,
                        saml_x509_cert: payload.saml_x509_cert,
                    },
                    IdentityProviderConfigDomainsKindEnumApi.Saml,
                    payload.domain_ids
                )
                breakpoint()
                actions.resetSamlConfig({
                    id: config.id,
                    name: config.name || payload.name,
                    domain_ids: [...config.saml_domain_ids],
                    saml_acs_url: config.saml_acs_url || '',
                    saml_entity_id: config.saml_entity_id || '',
                    saml_x509_cert: config.saml_x509_cert || '',
                })
                actions.reloadIdentitySettings()
                lemonToast.success(`SAML configuration “${config.name}” saved.`)
            },
        },
        scimConfig: {
            defaults: {
                name: DEFAULT_IDENTITY_PROVIDER_NAMES.scim,
                domain_ids: [],
                scim_enabled: false,
            } as SCIMConfigType,
            errors: (payload) => ({
                domain_ids: payload.domain_ids.length === 0 ? ['Select at least one domain.'] : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const config = await saveIdentityProviderConfig(
                    currentOrganizationId(),
                    payload.id,
                    { name: payload.name, scim_enabled: payload.scim_enabled },
                    IdentityProviderConfigDomainsKindEnumApi.Scim,
                    payload.domain_ids
                )
                breakpoint()
                actions.setScimPlaintextToken(config.scim_bearer_token)
                actions.resetScimConfig({
                    id: config.id,
                    name: config.name || payload.name,
                    domain_ids: [...config.scim_domain_ids],
                    scim_enabled: config.scim_enabled,
                })
                actions.reloadIdentitySettings()
                lemonToast.success(`SCIM configuration “${config.name}” saved.`)
            },
        },
        idJagConfig: {
            defaults: { name: DEFAULT_IDENTITY_PROVIDER_NAMES.idJag, domain_ids: [] } as IdJagConfigType,
            errors: (payload) => ({
                domain_ids: payload.domain_ids.length === 0 ? ['Select at least one domain.'] : undefined,
                id_jag_issuer_url:
                    payload.id_jag_issuer_url && !payload.id_jag_issuer_url.match(SECURE_URL_REGEX)
                        ? 'Enter a valid URL, including https://'
                        : undefined,
                id_jag_jwks_url:
                    payload.id_jag_jwks_url && !payload.id_jag_jwks_url.match(SECURE_URL_REGEX)
                        ? 'Enter a valid URL, including https://'
                        : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const config = await saveIdentityProviderConfig(
                    currentOrganizationId(),
                    payload.id,
                    {
                        name: payload.name,
                        id_jag_issuer_url: payload.id_jag_issuer_url?.trim() || null,
                        id_jag_jwks_url: payload.id_jag_jwks_url?.trim() || null,
                        id_jag_allowed_clients: payload.id_jag_allowed_clients || [],
                    },
                    IdentityProviderConfigDomainsKindEnumApi.IdJag,
                    payload.domain_ids
                )
                breakpoint()
                actions.resetIdJagConfig({
                    id: config.id,
                    name: config.name || payload.name,
                    domain_ids: [...config.id_jag_domain_ids],
                    id_jag_issuer_url: config.id_jag_issuer_url || '',
                    id_jag_jwks_url: config.id_jag_jwks_url || '',
                    id_jag_allowed_clients: config.id_jag_allowed_clients || [],
                })
                actions.reloadIdentitySettings()
                lemonToast.success(`XAA configuration “${config.name}” saved.`)
            },
        },
    })),
])
