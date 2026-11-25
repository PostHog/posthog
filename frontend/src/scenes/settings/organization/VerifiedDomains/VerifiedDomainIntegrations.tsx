import { useValues } from 'kea'

import { IconLock, IconPeople, IconShieldLock, IconShuffle } from '@posthog/icons'
import { Badge, Text, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ConfigScopeEnumApi } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'

import { getIdentityProviderConfigForDomain, verifiedDomainsLogic } from './verifiedDomainsLogic'

// One distinctive icon per integration type, reused across each integration's status badges.
const SAML_ICON = <IconShieldLock />
const SCIM_ICON = <IconPeople />
const XAA_ICON = <IconShuffle />

function IntegrationBadge({
    label,
    type,
    tooltip,
    icon,
    to,
}: {
    label: string
    type: LemonTagType
    tooltip: string
    icon?: JSX.Element
    to?: string
}): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillTooltip>
                <TooltipTrigger
                    render={to ? <LinkPrimitive to={to} className="inline-flex" /> : <span className="inline-flex" />}
                >
                    <Badge variant={type === 'success' ? 'success' : 'default'}>
                        {icon}
                        {label}
                    </Badge>
                </TooltipTrigger>
                <TooltipContent>{tooltip}</TooltipContent>
            </QuillTooltip>
        )
    }

    const tag = (
        <LemonTag type={type} icon={icon}>
            {label}
        </LemonTag>
    )
    // The tooltip needs a plain element it can attach hover handlers to; LemonTag can't reliably act as a
    // Base UI tooltip trigger (it would also pick up the injected onClick and look clickable), so wrap it.
    return (
        <Tooltip title={tooltip}>
            {to ? (
                <Link to={to} className="inline-flex">
                    {tag}
                </Link>
            ) : (
                <span className="inline-flex">{tag}</span>
            )}
        </Tooltip>
    )
}

export function VerifiedDomainIntegrations({ id }: { id: string }): JSX.Element {
    const { isSAMLAvailable, isOIDCAvailable, isSCIMAvailable, isXAAAuthenticationAvailable, identityProviderConfigs } =
        useValues(verifiedDomainsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const showXAAControls = !!featureFlags[FEATURE_FLAGS.XAA_AUTHENTICATION] && isXAAAuthenticationAvailable
    const samlConfig = getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Saml)
    const scimConfig = getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Scim)
    const oidcConfig = getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Oidc)
    const idJagConfig = getIdentityProviderConfigForDomain(identityProviderConfigs, id, ConfigScopeEnumApi.Xaa)
    const billingLink = urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])
    const badges: JSX.Element[] = []

    if (!isSAMLAvailable) {
        badges.push(
            <IntegrationBadge
                key="saml"
                label="SAML"
                type="muted"
                icon={SAML_ICON}
                tooltip="Upgrade your plan to enable SAML"
                to={billingLink}
            />
        )
    } else if (samlConfig?.has_saml) {
        badges.push(
            <IntegrationBadge key="saml" label="SAML" type="success" icon={SAML_ICON} tooltip="SAML is enabled" />
        )
    } else {
        badges.push(
            <IntegrationBadge key="saml" label="SAML" type="muted" icon={SAML_ICON} tooltip="SAML is not enabled" />
        )
    }

    badges.push(
        <IntegrationBadge
            key="oidc"
            label="OIDC"
            type={isOIDCAvailable && oidcConfig?.has_oidc ? 'success' : 'muted'}
            icon={<IconLock />}
            tooltip={
                !isOIDCAvailable
                    ? 'Upgrade your plan to enable OIDC'
                    : oidcConfig?.has_oidc
                      ? 'OIDC is enabled'
                      : 'OIDC is not enabled'
            }
            to={!isOIDCAvailable ? billingLink : undefined}
        />
    )

    if (!isSCIMAvailable) {
        badges.push(
            <IntegrationBadge
                key="scim"
                label="SCIM"
                type="muted"
                icon={SCIM_ICON}
                tooltip="Upgrade your plan to enable SCIM"
                to={billingLink}
            />
        )
    } else if (scimConfig?.has_scim) {
        badges.push(
            <IntegrationBadge key="scim" label="SCIM" type="success" icon={SCIM_ICON} tooltip="SCIM is enabled" />
        )
    } else {
        badges.push(
            <IntegrationBadge key="scim" label="SCIM" type="muted" icon={SCIM_ICON} tooltip="SCIM is not enabled" />
        )
    }

    if (showXAAControls && idJagConfig?.has_id_jag) {
        badges.push(<IntegrationBadge key="xaa" label="XAA" type="success" icon={XAA_ICON} tooltip="XAA is enabled" />)
    }

    if (badges.length === 0) {
        return todayRailNav ? (
            <Text size="xs" variant="muted" render={<span />}>
                Not configured
            </Text>
        ) : (
            <span className="text-muted">Not configured</span>
        )
    }

    return <div className="flex items-center gap-1 flex-wrap">{badges}</div>
}
