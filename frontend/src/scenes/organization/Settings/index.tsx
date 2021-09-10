import React, { useEffect, useState } from 'react'
import { Button, Card, Input, Divider, Select, Skeleton, Switch } from 'antd'
import { AvailableFeature, UserType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { Invites } from './Invites'
import { Members } from './Members'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { DangerZone } from './DangerZone'
import { RestrictedArea, RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from '../../../lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { IconExternalLink } from 'lib/components/icons'
import { sceneLogic } from '../../sceneLogic'
import { featureFlagLogic } from '../../../lib/logic/featureFlagLogic'

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

function DomainWhitelist({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { socialAuthAvailable } = useValues(preflightLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const [localList, setLocalList] = useState([] as string[])

    useEffect(() => setLocalList(currentOrganization?.domain_whitelist || []), [currentOrganization?.domain_whitelist])

    return (
        <div>
            <h2 id="domain-whitelist" className="subtitle">
                Domain Whitelist
            </h2>
            {socialAuthAvailable ? (
                <div>
                    Trusted domains for authentication. When <b>new users</b> log in through a social provider (e.g.
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
                                disabled={isRestricted}
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
                        href="https://posthog.com/docs/features/sso?utm_campaign=domain-whitelist&utm_medium=in-product"
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

function EmailPreferences({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    return (
        <div>
            <h2 id="name" className="subtitle">
                Notification Preferences
            </h2>
            <div>
                <Switch
                    // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                    id="is-member-join-email-enabled-switch"
                    data-attr="is-member-join-email-enabled-switch"
                    onChange={(checked) => {
                        updateOrganization({ is_member_join_email_enabled: checked })
                    }}
                    checked={currentOrganization?.is_member_join_email_enabled}
                    loading={currentOrganizationLoading}
                    disabled={isRestricted || !currentOrganization}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="is-member-join-email-enabled-switch"
                >
                    Email all current members when a new member joins
                </label>
            </div>
        </div>
    )
}

function Permissioning({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <div>
            <h2 id="name" className="subtitle">
                Permissioning
            </h2>
            <div>
                <Switch
                    // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                    id="per-project-access-switch"
                    onChange={(checked) => {
                        guardAvailableFeature(
                            AvailableFeature.PER_PROJECT_ACCESS,
                            'per-project access',
                            'Gain the ability to set permissions granularly inside the organization. Make sure the right people have access to data.',
                            () => updateOrganization({ per_project_access: checked })
                        )
                    }}
                    checked={
                        currentOrganization?.available_features.includes(AvailableFeature.PER_PROJECT_ACCESS) &&
                        currentOrganization?.per_project_access
                    }
                    loading={currentOrganizationLoading}
                    disabled={isRestricted || !currentOrganization}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="per-project-access-switch"
                >
                    Per-project access
                </label>
                <p>
                    Per-project access means that organization members below Administrator level by default lack access
                    to projects.
                    <br />
                    Access to each project can then be granted individually only for members who need it.
                </p>
            </div>
        </div>
    )
}

export function OrganizationSettings({ user }: { user: UserType }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <PageHeader
                title="Organization Settings"
                caption="View and manage your organization here. Build an even better product together."
            />
            <Card>
                <RestrictedArea Component={DisplayName} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                {!preflight?.cloud && (
                    <>
                        <RestrictedArea
                            Component={DomainWhitelist}
                            minimumAccessLevel={OrganizationMembershipLevel.Admin}
                        />
                        <Divider />
                    </>
                )}
                <Invites />
                <Divider />
                <Members user={user} />
                <Divider />
                {featureFlags[FEATURE_FLAGS.PER_PROJECT_ACCESS] && (
                    <>
                        <RestrictedArea
                            Component={Permissioning}
                            minimumAccessLevel={OrganizationMembershipLevel.Admin}
                        />
                        <Divider />
                    </>
                )}
                <RestrictedArea Component={EmailPreferences} minimumAccessLevel={OrganizationMembershipLevel.Admin} />
                <Divider />
                <RestrictedArea Component={DangerZone} minimumAccessLevel={OrganizationMembershipLevel.Owner} />
            </Card>
        </>
    )
}
