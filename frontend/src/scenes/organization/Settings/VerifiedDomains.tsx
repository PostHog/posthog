import { Switch } from 'antd'
import { useValues } from 'kea'
import { IconCheckmark, IconDelete, IconExclamation, IconWarningAmber } from 'lib/components/icons'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Tooltip } from 'lib/components/Tooltip'
import React from 'react'
import { OrganizationDomainType } from '~/types'
import { verifiedDomainsLogic } from '../verifiedDomainsLogic'
import { InfoCircleOutlined } from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'

/** TODO: Pay gate */
export function VerifiedDomains(): JSX.Element {
    const { verifiedDomains, verifiedDomainsLoading, currentOrganization } = useValues(verifiedDomainsLogic)

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
            render: function AutomaticProvisioning(_, { jit_provisioning_enabled }) {
                return <Switch checked={jit_provisioning_enabled} />
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
            render: function SSOEnforcement(_, { sso_enforcement }) {
                return <>{sso_enforcement}</>
            },
        },
        {
            key: 'actions',
            width: 32,
            align: 'center',
            render: function RenderActions(_, { is_verified }) {
                return is_verified ? (
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() => console.log(1)}
                                    fullWidth
                                >
                                    <IconDelete /> Remove domain
                                </LemonButton>
                            </>
                        }
                        style={{ display: 'inline-block' }}
                    />
                ) : (
                    <LemonButton type="primary">Verify</LemonButton>
                )
            },
        },
    ]
    return (
        <div>
            <div id="domain-whitelist" /> {/** For backwards link compatibility. Remove after 6/1/22. */}
            <h2 id="verified-domains" className="subtitle">
                Verified domains
            </h2>
            <p className="text-muted-alt">
                Enable users to sign up automatically with an email address on verified domains and enforce SSO for
                accounts under your domains.
            </p>
            <LemonTable
                dataSource={verifiedDomains}
                columns={columns}
                loading={verifiedDomainsLoading}
                rowKey="id"
                emptyState="You haven't registered any verified domains."
            />
        </div>
    )
}
