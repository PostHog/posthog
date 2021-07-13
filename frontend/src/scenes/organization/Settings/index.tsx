import React, { useEffect, useState } from 'react'
import { Button, Card, Input, Divider, Select, Skeleton } from 'antd'
import { UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { DangerZone } from './DangerZone'
import { RestrictedArea, RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from '../../../lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { IconExternalLink } from 'lib/components/icons'

function DisplayName({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { renameCurrentOrganization } = useActions(organizationLogic)

    const [name, setName] = useState(currentOrganization?.name || '')

    return (
        <div>
            <h2 id="name" className="subtitle">
                Display Name
            </h2>
            <Input
                value={name}
                onChange={(event) => {
                    setName(event.target.value)
                }}
                style={{ maxWidth: '40rem', marginBottom: '1rem', display: 'block' }}
                disabled={isRestricted}
            />
            <Button
                type="primary"
                onClick={(e) => {
                    e.preventDefault()
                    renameCurrentOrganization(name)
                }}
                disabled={isRestricted || !name || !currentOrganization || name === currentOrganization.name}
                loading={currentOrganizationLoading}
            >
                Rename Organization
            </Button>
        </div>
    )
}

function DomainWhitelist(): JSX.Element {
    const { socialAuthAvailable } = useValues(preflightLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const [localList, setLocalList] = useState([] as string[])

    useEffect(() => setLocalList(currentOrganization?.domain_whitelist || []), [currentOrganization?.domain_whitelist])

    return (
        <div>
            <h2 id="name" className="subtitle">
                Domain Whitelist
            </h2>
            {socialAuthAvailable ? (
                <div>
                    Add domains to your whitelisted. When <b>new users</b> log in through a social provider (e.g.
                    Google) using an email address on any of your whitelisted domains, they'll be{' '}
                    <b>automatically added to this organization.</b>
                    <div className="mt-05">
                        {currentOrganization ? (
                            <Select
                                mode="tags"
                                placeholder="Add whitelisted domains (e.g. hogflix.com or movies.hogflix.com)"
                                onChange={(val) => setLocalList(val as string[])}
                                loading={currentOrganizationLoading}
                                style={{ width: '40rem', maxWidth: '100%' }}
                                onBlur={() => updateOrganization({ domain_whitelist: localList })}
                                value={localList}
                            >
                                {currentOrganization.domain_whitelist.map((domain) => (
                                    <Select.Option key={domain} value={domain}>
                                        {domain}
                                    </Select.Option>
                                ))}
                            </Select>
                        ) : (
                            <Skeleton active />
                        )}
                    </div>
                </div>
            ) : (
                <div className="text-muted">
                    This feature is only available when social authentication is enabled.{' '}
                    <a
                        href="https://posthog.com/docs/features/log-in-with-github-gitlab?utm_campaign=domain-whitelist&utm_medium=in-product"
                        target="_blank"
                        rel="noopener"
                    >
                        Learn more <IconExternalLink />
                    </a>
                </div>
            )}
        </div>
    )
}

export function OrganizationSettings({ user }: { user: UserType }): JSX.Element {
    return (
        <>
            <PageHeader
                title="Organization Settings"
                caption="View and manage your organization here. Build an even better product together."
            />
            <Card>
                <RestrictedArea Component={DisplayName} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                <DomainWhitelist />
                <Divider />
                <Invites />
                <Divider />
                <Members user={user} />
                <Divider />
                <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
            </Card>
        </>
    )
}
