import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconShieldLock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { OrganizationMembershipLevel } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import type { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { identityProviderConfigLogic } from './identityProviderConfigLogic'
import type { IdentityProviderConfigLogicProps } from './identityProviderConfigLogic'
import { IDENTITY_PROVIDER_FEATURES, isIdentityProviderConfigScope } from './identityProviderConfigUtils'
import { IdentityProviderDomainScope } from './IdentityProviderDomainScope'
import { SAMLConfigFields } from './SAMLConfigFields'
import { SCIMConfigFields } from './SCIMConfigFields'
import { XAAConfigFields } from './XAAConfigFields'

export const scene: SceneExport<IdentityProviderConfigLogicProps> = {
    component: IdentityProviderConfigScene,
    logic: identityProviderConfigLogic,
    paramsToProps: ({ params }) => ({
        configScope: isIdentityProviderConfigScope(params.feature) ? params.feature : null,
        configId: params.configId,
    }),
}

export function IdentityProviderConfigScene(): JSX.Element | null {
    const {
        configScope,
        identityProviderConfig,
        identityProviderConfigLoaded,
        identityProviderConfigLoading,
        identityProviderConfigLoadFailed,
        identityProviderConfigForm,
        identityProviderConfigFormChanged,
        isIdentityProviderConfigFormSubmitting,
        hasSamlDomainScopeConflict,
        isConfigScopeValid,
        isRedesignEnabled,
        organizationDomains,
        organizationDomainsLoadFailed,
        organizationDomainsLoading,
        revealedScimToken,
        regeneratedScimTokenLoading,
    } = useValues(identityProviderConfigLogic)
    const { loadIdentityProviderConfig, loadOrganizationDomains, regenerateScimToken } =
        useActions(identityProviderConfigLogic)
    const { preflight } = useValues(preflightLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    if (!isRedesignEnabled) {
        return null
    }

    if (!configScope) {
        return <NotFound object="identity provider configuration" />
    }

    const feature = IDENTITY_PROVIDER_FEATURES[configScope]
    const siteUrl = preflight?.site_url ?? window.location.origin
    const isLoading =
        (!identityProviderConfigLoaded && !identityProviderConfigLoadFailed) ||
        (organizationDomains === null && !organizationDomainsLoadFailed)
    const loadFailed = identityProviderConfigLoadFailed || organizationDomainsLoadFailed

    if (identityProviderConfigLoaded && !isConfigScopeValid) {
        return <NotFound object={`${feature.name} configuration`} />
    }

    return (
        <SceneContent className="pb-8">
            <SceneTitleSection
                name={`Configure ${feature.name}`}
                resourceType={{ type: 'identity_provider', forceIcon: <IconShieldLock /> }}
            />
            <TimeSensitiveAuthenticationArea>
                <PayGateMini feature={feature.availableFeature} featureDetail={`${configScope}-configuration`}>
                    {loadFailed ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => {
                                    if (identityProviderConfigLoadFailed) {
                                        loadIdentityProviderConfig()
                                    }
                                    if (organizationDomainsLoadFailed) {
                                        loadOrganizationDomains()
                                    }
                                },
                                loading: identityProviderConfigLoading || organizationDomainsLoading,
                            }}
                        >
                            Couldn't load this identity provider configuration.
                        </LemonBanner>
                    ) : isLoading ? (
                        <div className="flex min-h-64 items-center justify-center">
                            <Spinner size="large" captureTime />
                        </div>
                    ) : (
                        <Form
                            logic={identityProviderConfigLogic}
                            formKey="identityProviderConfigForm"
                            enableFormOnSubmit
                            className="max-w-200 space-y-6"
                        >
                            {configScope === ConfigScopeEnumApi.Saml ? (
                                <SAMLConfigFields
                                    siteUrl={siteUrl}
                                    relayState={identityProviderConfig?.saml_relay_state ?? null}
                                    isReady={Boolean(
                                        identityProviderConfigForm.saml_acs_url &&
                                        identityProviderConfigForm.saml_entity_id &&
                                        identityProviderConfigForm.saml_x509_cert
                                    )}
                                />
                            ) : configScope === ConfigScopeEnumApi.Scim ? (
                                <SCIMConfigFields
                                    scimEnabled={identityProviderConfigForm.scim_enabled}
                                    scimBaseUrl={identityProviderConfig?.scim_base_url ?? null}
                                    revealedToken={revealedScimToken}
                                    canRegenerateToken={Boolean(identityProviderConfig?.scim_enabled)}
                                    tokenLoading={regeneratedScimTokenLoading}
                                    disabled={isIdentityProviderConfigFormSubmitting}
                                    onRegenerateToken={regenerateScimToken}
                                />
                            ) : (
                                <XAAConfigFields isReady={Boolean(identityProviderConfigForm.id_jag_issuer_url)} />
                            )}

                            <LemonDivider />
                            <IdentityProviderDomainScope
                                configScope={configScope}
                                domainScope={identityProviderConfigForm.domain_scope}
                                domains={organizationDomains ?? []}
                                disabled={isIdentityProviderConfigFormSubmitting}
                                hasSamlDomainScopeConflict={hasSamlDomainScopeConflict}
                                showScopeWarning={identityProviderConfig?.config_scope === null}
                            />
                            <div className="flex flex-wrap gap-2">
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    loading={isIdentityProviderConfigFormSubmitting}
                                    disabledReason={
                                        restrictionReason ||
                                        (!identityProviderConfigFormChanged ? 'No changes to save' : undefined)
                                    }
                                    data-attr={`save-${configScope}-identity-provider`}
                                >
                                    Save configuration
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    to={urls.settings('organization-authentication')}
                                    disabled={isIdentityProviderConfigFormSubmitting}
                                >
                                    Cancel
                                </LemonButton>
                            </div>
                        </Form>
                    )}
                </PayGateMini>
            </TimeSensitiveAuthenticationArea>
        </SceneContent>
    )
}
