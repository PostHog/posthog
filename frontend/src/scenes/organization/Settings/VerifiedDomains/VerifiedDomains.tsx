import { Button, Modal, Switch } from 'antd'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconDelete, IconExclamation, IconWarningAmber } from 'lib/components/icons'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Tooltip } from 'lib/components/Tooltip'
import React from 'react'
import { AvailableFeature, OrganizationDomainType } from '~/types'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { InfoCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { AddDomainModal } from './AddDomainModal'
import { SSOSelect } from './SSOSelect'
import { VerifyDomainModal } from './VerifyDomainModal'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

export function VerifiedDomains(): JSX.Element {
    const { verifiedDomainsLoading, updatingDomainLoading, isFeatureAvailable } = useValues(verifiedDomainsLogic)
    const { setAddModalShown } = useActions(verifiedDomainsLogic)

    return (
        <>
            <div className="flex-center">
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
                {isFeatureAvailable && (
                    <div>
                        <Button
                            type="primary"
                            icon={<PlusOutlined />}
                            onClick={() => setAddModalShown(true)}
                            disabled={verifiedDomainsLoading || updatingDomainLoading}
                        >
                            Add domain
                        </Button>
                    </div>
                )}
            </div>
            <PayGateMini feature={AvailableFeature.SSO_ENFORCEMENT} overrideShouldShowGate={isFeatureAvailable}>
                <VerifiedDomainsTable />
            </PayGateMini>
        </>
    )
}

function VerifiedDomainsTable(): JSX.Element {
    const { verifiedDomains, verifiedDomainsLoading, currentOrganization, updatingDomainLoading } =
        useValues(verifiedDomainsLogic)
    const { updateDomain, deleteVerifiedDomain, setVerifyModal } = useActions(verifiedDomainsLogic)

    const columns: LemonTableColumns<OrganizationDomainType> = [
        {
            key: 'domain',
            title: 'Domain name',
            dataIndex: 'domain',
            render: function RenderDomainName(_, { domain }) {
                return <LemonTag>{domain}</LemonTag>
            },
        },
        {
            key: 'is_verified',
            title: 'Verification',
            render: function Verified(_, { is_verified, verified_at }) {
                const iconStyle = { marginRight: 4, fontSize: '1.15em', paddingTop: 2 }
                return is_verified ? (
                    <div className="flex-center text-success">
                        <IconCheckmark style={iconStyle} /> Verified
                    </div>
                ) : verified_at ? (
                    <div className="flex-center text-danger">
                        <IconExclamation style={iconStyle} /> Verification expired
                    </div>
                ) : (
                    <div className="flex-center text-warning">
                        <IconWarningAmber style={iconStyle} /> Pending verification
                    </div>
                )
            },
        },
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
                    <Switch
                        checked={jit_provisioning_enabled}
                        disabled={updatingDomainLoading || !is_verified}
                        onChange={(checked) => updateDomain({ id, jit_provisioning_enabled: checked })}
                    />
                ) : (
                    <span className="text-muted-alt">Verify domain to enable</span>
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
            render: function SSOEnforcement(_, { sso_enforcement, is_verified, id }) {
                return is_verified ? (
                    <SSOSelect
                        value={sso_enforcement}
                        loading={updatingDomainLoading}
                        onChange={(val) => updateDomain({ id, sso_enforcement: val })}
                    />
                ) : (
                    <span className="text-muted-alt">Verify domain to enable</span>
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
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() =>
                                        Modal.confirm({
                                            title: `Remove ${domain}?`,
                                            icon: null,
                                            okText: 'Remove domain',
                                            okType: 'primary',
                                            okButtonProps: { className: 'btn-danger' },
                                            content: (
                                                <div>
                                                    This cannot be undone. If you have SAML configured or SSO enforced,
                                                    it will be immediately disabled.
                                                </div>
                                            ),
                                            onOk() {
                                                deleteVerifiedDomain(id)
                                            },
                                            cancelText: 'Cancel',
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
            <VerifyDomainModal />
        </div>
    )
}
