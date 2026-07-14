import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPeople, IconRefresh } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { IdentityProviderDomainPicker } from './IdentityProviderDomainPicker'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function SCIMSettings(): JSX.Element {
    const {
        isSCIMAvailable,
        isScimConfigSubmitting,
        regeneratingScimToken,
        scimConfig,
        scimPlaintextToken,
        verifiedDomainsList,
    } = useValues(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)
    const { regenerateScimToken, setScimLogsModalId } = useActions(verifiedDomainsLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })
    const selectedDomains = verifiedDomainsList.filter(({ id }) => scimConfig.domain_ids.includes(id))
    const siteUrl = (preflight?.site_url ?? window.location.origin).replace(/\/$/, '')

    return (
        <section className="space-y-3">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="flex items-center gap-2">
                        <IconPeople /> SCIM
                    </h2>
                    <p className="text-muted">
                        Configure provisioning from your identity provider for people and groups.{' '}
                        <Link to="https://posthog.com/docs/data/sso/scim" target="_blank" targetBlankIcon>
                            Read the docs
                        </Link>
                    </p>
                </div>
                <LemonTag type={scimConfig.scim_enabled ? 'success' : 'muted'}>
                    {scimConfig.scim_enabled ? 'Provisioning enabled' : scimConfig.id ? 'Disabled' : 'Not configured'}
                </LemonTag>
            </div>
            <div>
                {!isSCIMAvailable ? (
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                        Upgrade your plan to configure SCIM.
                    </Link>
                ) : (
                    <Form logic={verifiedDomainsLogic} formKey="scimConfig" enableFormOnSubmit className="space-y-4">
                        <LemonField name="scim_enabled" label="Provisioning status">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value || false}
                                    onChange={onChange}
                                    label="SCIM provisioning"
                                />
                            )}
                        </LemonField>
                        {scimConfig.scim_enabled && (
                            <>
                                <IdentityProviderDomainPicker />
                                {selectedDomains.length > 0 && (
                                    <div className="space-y-2">
                                        <h3>SCIM base URLs</h3>
                                        <LemonTable
                                            dataSource={selectedDomains}
                                            rowKey="id"
                                            columns={[
                                                {
                                                    key: 'domain',
                                                    title: 'Domain',
                                                    render: (_, domain) => domain.domain,
                                                },
                                                {
                                                    key: 'base_url',
                                                    title: 'Base URL',
                                                    render: (_, domain) => (
                                                        <CopyToClipboardInline>
                                                            {domain.scim_base_url ?? `${siteUrl}/scim/v2/${domain.id}`}
                                                        </CopyToClipboardInline>
                                                    ),
                                                },
                                                {
                                                    key: 'actions',
                                                    width: 0,
                                                    render: (_, domain) =>
                                                        scimConfig.id ? (
                                                            <LemonButton
                                                                size="small"
                                                                onClick={() => setScimLogsModalId(domain.id)}
                                                            >
                                                                View logs
                                                            </LemonButton>
                                                        ) : null,
                                                },
                                            ]}
                                        />
                                    </div>
                                )}
                                {scimPlaintextToken && (
                                    <LemonBanner type="success">
                                        <div className="space-y-2">
                                            <p>Copy this bearer token now. It will not be shown again.</p>
                                            <CopyToClipboardInline>{scimPlaintextToken}</CopyToClipboardInline>
                                        </div>
                                    </LemonBanner>
                                )}
                            </>
                        )}
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isScimConfigSubmitting}
                                disabledReason={restrictionReason}
                            >
                                Save SCIM settings
                            </LemonButton>
                            {scimConfig.id && scimConfig.scim_enabled && (
                                <LemonButton
                                    type="secondary"
                                    icon={<IconRefresh />}
                                    loading={regeneratingScimToken}
                                    disabledReason={restrictionReason}
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: 'Regenerate SCIM bearer token?',
                                            description: 'The current token will stop working immediately.',
                                            primaryButton: {
                                                children: 'Regenerate token',
                                                onClick: () => regenerateScimToken(scimConfig.id as string),
                                            },
                                            secondaryButton: { children: 'Cancel' },
                                        })
                                    }
                                >
                                    Regenerate token
                                </LemonButton>
                            )}
                        </div>
                    </Form>
                )}
            </div>
        </section>
    )
}
