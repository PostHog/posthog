import { useActions, useValues } from 'kea'
import { IconCheckmark, IconDelete, IconExclamation, IconWarning, IconLock, IconOffline } from 'lib/lemon-ui/icons'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { OrganizationDomainType } from '~/types'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { AddDomainModal } from './AddDomainModal'
import { SSOSelect } from './SSOSelect'
import { VerifyDomainModal } from './VerifyDomainModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Link } from 'lib/lemon-ui/Link'
import { UPGRADE_LINK } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { ConfigureSAMLModal } from './ConfigureSAMLModal'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

const iconStyle = { marginRight: 4, fontSize: '1.15em', paddingTop: 2 }

export function VerifiedDomains(): JSX.Element {
    const { verifiedDomainsLoading, updatingDomainLoading } = useValues(verifiedDomainsLogic)
    const { setAddModalShown } = useActions(verifiedDomainsLogic)

    return (
        <>
            <div className="flex items-center">
                <div style={{ flexGrow: 1 }}>
                    <div id="domain-whitelist" /> {/** For backwards link compatibility. Remove after 2022-06-01. */}
                    <h2 id="authentication-domains" className="subtitle">
                        Authentication domains
                    </h2>
                    <p className="text-muted-alt">
                        Enable users to sign up automatically with an email address on verified domains and enforce SSO
                        for accounts under your domains.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    onClick={() => setAddModalShown(true)}
                    disabled={verifiedDomainsLoading || updatingDomainLoading}
                >
                    Add domain
                </LemonButton>
            </div>
            <VerifiedDomainsTable />
        </>
    )
}

function VerifiedDomainsTable(): JSX.Element {
    const {
        verifiedDomains,
        verifiedDomainsLoading,
        currentOrganization,
        updatingDomainLoading,
        isSSOEnforcementAvailable,
        isSAMLAvailable,
    } = useValues(verifiedDomainsLogic)
    const { updateDomain, deleteVerifiedDomain, setVerifyModal, setConfigureSAMLModalId } =
        useActions(verifiedDomainsLogic)
    const { preflight } = useValues(preflightLogic)

    const columns: LemonTableColumns<OrganizationDomainType> = [
        {
            key: 'domain',
            title: 'Domain name',
            dataIndex: 'domain',
            render: function RenderDomainName(_, { domain }) {
                return <LemonTag>{domain}</LemonTag>
            },
        },
        ...(preflight?.cloud
            ? ([
                  {
                      key: 'is_verified',
                      title: (
                          <>
                              Verification
                              <Tooltip title="Verification (through DNS) is required to use domains for authentication (e.g. SAML or enforce SSO).">
                                  <InfoCircleOutlined style={{ marginLeft: 4 }} />
                              </Tooltip>
                          </>
                      ),
                      render: function Verified(_, { is_verified, verified_at }) {
                          return is_verified ? (
                              <div className="flex items-center text-success">
                                  <IconCheckmark style={iconStyle} /> Verified
                              </div>
                          ) : verified_at ? (
                              <div className="flex items-center text-danger">
                                  <IconExclamation style={iconStyle} /> Verification expired
                              </div>
                          ) : (
                              <div className="flex items-center text-warning">
                                  <IconWarning style={iconStyle} /> Pending verification
                              </div>
                          )
                      },
                  },
              ] as LemonTableColumns<OrganizationDomainType>)
            : []),
        {
            key: 'jit_provisioning_enabled',
            title: (
                <>
                    Automatic provisioning{' '}
                    <Tooltip
                        title={`Enables just-in-time provisioning. If a user logs in with SSO with an email address on this domain an account will be created in ${
                            currentOrganization?.name || 'this organization'
                        } if it does not exist.`}
                    >
                        <InfoCircleOutlined />
                    </Tooltip>
                </>
            ),
            render: function AutomaticProvisioning(_, { jit_provisioning_enabled, id, is_verified }) {
                return is_verified ? (
                    <div className="flex items-center">
                        <LemonSwitch
                            checked={jit_provisioning_enabled}
                            disabled={updatingDomainLoading || !is_verified}
                            onChange={(checked) => updateDomain({ id, jit_provisioning_enabled: checked })}
                            label={
                                <span className="font-normal">{jit_provisioning_enabled ? 'Enabled' : 'Disabled'}</span>
                            }
                        />
                    </div>
                ) : (
                    <i className="text-muted-alt">Verify domain to enable automatic provisioning</i>
                )
            },
        },
        {
            key: 'sso_enforcement',
            title: (
                <>
                    Enforce SSO{' '}
                    <Tooltip title="Require users with email addresses on this domain to always log in using a specific SSO provider.">
                        <InfoCircleOutlined />
                    </Tooltip>
                </>
            ),
            render: function SSOEnforcement(_, { sso_enforcement, is_verified, id, has_saml }, index) {
                if (!isSSOEnforcementAvailable) {
                    return index === 0 ? (
                        <Link
                            to={UPGRADE_LINK(preflight?.cloud).url}
                            target={UPGRADE_LINK(preflight?.cloud).target}
                            className="flex items-center"
                        >
                            <IconLock style={{ color: 'var(--warning)', marginLeft: 4 }} /> Upgrade to enable SSO
                            enforcement
                        </Link>
                    ) : (
                        <></>
                    )
                }
                return is_verified ? (
                    <SSOSelect
                        value={sso_enforcement}
                        loading={updatingDomainLoading}
                        onChange={(val) => updateDomain({ id, sso_enforcement: val })}
                        samlAvailable={has_saml}
                    />
                ) : (
                    <i className="text-muted-alt">Verify domain to enable</i>
                )
            },
        },
        {
            key: 'saml',
            title: 'SAML',
            render: function SAML(_, { is_verified, saml_acs_url, saml_entity_id, saml_x509_cert, has_saml }, index) {
                if (!isSAMLAvailable) {
                    return index === 0 ? (
                        <Link
                            to={UPGRADE_LINK(preflight?.cloud).url}
                            target={UPGRADE_LINK(preflight?.cloud).target}
                            className="flex items-center"
                        >
                            <IconLock style={{ color: 'var(--warning)', marginLeft: 4 }} /> Upgrade to enable SAML
                        </Link>
                    ) : (
                        <></>
                    )
                }
                return is_verified ? (
                    <>
                        {has_saml ? (
                            <div className="flex items-center text-success">
                                <IconCheckmark style={iconStyle} /> SAML enabled
                            </div>
                        ) : saml_acs_url || saml_entity_id || saml_x509_cert ? (
                            <div className="flex items-center text-warning">
                                <IconWarning style={iconStyle} /> SAML partially configured
                            </div>
                        ) : (
                            <div className="flex items-center">
                                <IconOffline style={iconStyle} /> SAML not set up
                            </div>
                        )}
                    </>
                ) : (
                    <i className="text-muted-alt">Verify domain to enable</i>
                )
            },
        },
        {
            key: 'actions',
            width: 32,
            align: 'center',
            render: function RenderActions(_, { is_verified, id, domain }) {
                return is_verified ? (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => setConfigureSAMLModalId(id)}
                                    fullWidth
                                    disabled={!isSAMLAvailable}
                                    title={isSAMLAvailable ? undefined : 'Upgrade to enable SAML'}
                                >
                                    Configure SAML
                                </LemonButton>
                                <LemonButton
                                    status="danger"
                                    onClick={() =>
                                        LemonDialog.open({
                                            title: `Remove ${domain}?`,
                                            description:
                                                'This cannot be undone. If you have SAML configured or SSO enforced,it will be immediately disabled.',
                                            primaryButton: {
                                                status: 'danger',
                                                children: 'Remove domain',
                                                onClick: () => deleteVerifiedDomain(id),
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                            },
                                        })
                                    }
                                    fullWidth
                                >
                                    <IconDelete /> Remove domain
                                </LemonButton>
                            </>
                        }
                        style={{ display: 'inline-block' }}
                    />
                ) : (
                    <LemonButton type="primary" onClick={() => setVerifyModal(id)}>
                        Verify
                    </LemonButton>
                )
            },
        },
    ]
    return (
        <div>
            <LemonTable
                dataSource={verifiedDomains}
                columns={columns}
                loading={verifiedDomainsLoading}
                rowKey="id"
                emptyState="You haven't registered any authentication domains yet."
            />
            <AddDomainModal />
            <ConfigureSAMLModal />
            <VerifyDomainModal />
        </div>
    )
}
