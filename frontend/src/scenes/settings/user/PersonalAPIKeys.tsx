import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Fragment, useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { IconEllipsis, IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonMenu,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { API_KEY_SCOPE_PRESETS, API_SCOPES, MAX_API_KEYS_PER_USER } from 'lib/scopes'
import { capitalizeFirstLetter, detailedTime, humanFriendlyDetailedTime } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import ScopeAccessSelector from './scopes/ScopeAccessSelector'

function EditKeyModal(): JSX.Element {
    const {
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        formScopeRadioValues,
        allAccessSelected,
        editingKey,
        allTeams,
        allOrganizations,
    } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey, resetScopes } = useActions(personalAPIKeysLogic)
    const { isCloudOrDev } = useValues(preflightLogic)

    const isNew = editingKeyId === 'new'

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} personal API key`}
                onClose={() => setEditingKeyId(null)}
                isOpen={!!editingKeyId}
                width="40rem"
                hasUnsavedInput={editingKeyChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setEditingKeyId(null)}>
                            Cancel
                        </LemonButton>

                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingKeySubmitting}
                            disabled={!editingKeyChanged}
                            onClick={() => submitEditingKey()}
                        >
                            {isNew ? 'Create key' : 'Save key'}
                        </LemonButton>
                    </>
                }
            >
                <>
                    <LemonField name="label" label="Label">
                        <LemonInput placeholder='For example "Reports bot" or "Zapier"' maxLength={40} />
                    </LemonField>
                    <ScopeAccessSelector
                        accessType={editingKey.access_type}
                        organizations={allOrganizations}
                        teams={allTeams ?? undefined}
                    />
                    <div className="flex items-center justify-between mt-4 mb-2">
                        <LemonLabel>Scopes</LemonLabel>
                        <LemonField name="preset">
                            <LemonSelect
                                size="small"
                                placeholder="Select preset"
                                options={API_KEY_SCOPE_PRESETS.filter((preset) => !preset.isCloudOnly || isCloudOrDev)}
                                dropdownMatchSelectWidth={false}
                                dropdownPlacement="bottom-end"
                            />
                        </LemonField>
                    </div>

                    <LemonField name="scopes">
                        {({ error }) => (
                            <>
                                <p className="mb-0">
                                    API keys are scoped to limit what actions they are able to do. We highly recommend
                                    you only give the key the permissions it needs to do its job. You can add or revoke
                                    scopes later.
                                </p>
                                <p className="m-0">
                                    Your API key can never take actions for which your account is missing permissions.
                                </p>

                                {error && (
                                    <div className="text-danger flex items-center gap-1 text-sm">
                                        <IconErrorOutline className="text-xl" /> {error}
                                    </div>
                                )}

                                {allAccessSelected ? (
                                    <LemonBanner
                                        type="warning"
                                        action={{
                                            children: 'Reset',
                                            onClick: () => resetScopes(),
                                        }}
                                    >
                                        <b>This API key has full access to all supported endpoints!</b> We highly
                                        recommend scoping this to only what it needs.
                                    </LemonBanner>
                                ) : (
                                    <div>
                                        {API_SCOPES.map(
                                            ({ key, disabledActions, warnings, disabledWhenProjectScoped, info }) => {
                                                const disabledDueToProjectScope =
                                                    disabledWhenProjectScoped && editingKey.access_type === 'teams'
                                                return (
                                                    <Fragment key={key}>
                                                        <div className="flex items-center justify-between gap-2 min-h-8">
                                                            <div
                                                                className={clsx(
                                                                    'flex items-center gap-1',
                                                                    disabledDueToProjectScope && 'text-muted'
                                                                )}
                                                            >
                                                                <b>{capitalizeFirstLetter(key.replace(/_/g, ' '))}</b>

                                                                {info ? (
                                                                    <Tooltip title={info}>
                                                                        <IconInfo className="text-secondary text-base" />
                                                                    </Tooltip>
                                                                ) : null}
                                                            </div>
                                                            <LemonSegmentedButton
                                                                onChange={(value) => setScopeRadioValue(key, value)}
                                                                value={formScopeRadioValues[key] ?? 'none'}
                                                                options={[
                                                                    { label: 'No access', value: 'none' },
                                                                    {
                                                                        label: 'Read',
                                                                        value: 'read',
                                                                        disabledReason: disabledActions?.includes(
                                                                            'read'
                                                                        )
                                                                            ? 'Does not apply to this resource'
                                                                            : disabledDueToProjectScope
                                                                              ? 'Not available for project scoped keys'
                                                                              : undefined,
                                                                    },
                                                                    {
                                                                        label: 'Write',
                                                                        value: 'write',
                                                                        disabledReason: disabledActions?.includes(
                                                                            'write'
                                                                        )
                                                                            ? 'Does not apply to this resource'
                                                                            : disabledDueToProjectScope
                                                                              ? 'Not available for project scoped keys'
                                                                              : undefined,
                                                                    },
                                                                ]}
                                                                size="xsmall"
                                                            />
                                                        </div>
                                                        {warnings?.[formScopeRadioValues[key]] && (
                                                            <div className="flex items-start gap-2 text-xs italic pb-2">
                                                                <IconWarning className="text-base text-secondary mt-0.5" />
                                                                <span>{warnings[formScopeRadioValues[key]]}</span>
                                                            </div>
                                                        )}
                                                    </Fragment>
                                                )
                                            }
                                        )}
                                    </div>
                                )}
                            </>
                        )}
                    </LemonField>
                </>
            </LemonModal>
        </Form>
    )
}

type TagListProps = { onMoreClick: () => void; tags: string[] }

export function TagList({ tags, onMoreClick }: TagListProps): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((x) => (
                <>
                    <LemonTag key={x}>{x}</LemonTag>
                </>
            ))}
            {tags.length > 4 && (
                <Tooltip title={tags.slice(4).join(', ')}>
                    <LemonTag onClick={onMoreClick}>+{tags.length - 4} more</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

type TagListWithRestrictionsProps = {
    onMoreClick: () => void
    tags: Array<{ id: string; name: string; restricted: boolean }>
}

export function TagListWithRestrictions({ tags, onMoreClick }: TagListWithRestrictionsProps): JSX.Element {
    return (
        <span className="flex flex-wrap gap-1 items-center">
            {tags.slice(0, 4).map((tag) => (
                <LemonTag key={tag.id} className={tag.restricted ? 'line-through opacity-60' : ''}>
                    {tag.name}
                </LemonTag>
            ))}
            {tags.length > 4 && (
                <Tooltip
                    title={tags
                        .slice(4)
                        .map((tag) => tag.name)
                        .join(', ')}
                >
                    <LemonTag onClick={onMoreClick}>+{tags.length - 4} more</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

function PersonalAPIKeysTable(): JSX.Element {
    const {
        keys,
        keysLoading,
        allOrganizations,
        allTeams,
        isPersonalApiKeyIdDisabled,
        getRestrictedOrganizationsForKey,
        getRestrictedTeamsForKey,
    } = useValues(personalAPIKeysLogic)
    const { deleteKey, loadKeys, setEditingKeyId, rollKey } = useActions(personalAPIKeysLogic)

    useEffect(() => loadKeys(), [loadKeys])

    return (
        <LemonTable
            dataSource={keys}
            loading={keysLoading}
            loadingSkeletonRows={3}
            className="mt-4"
            nouns={['personal API key', 'personal API keys']}
            rowClassName={(key) => (isPersonalApiKeyIdDisabled(key.id) ? 'opacity-50' : '')}
            columns={[
                {
                    title: 'Label',
                    dataIndex: 'label',
                    key: 'label',
                    render: function RenderLabel(label, key) {
                        return (
                            <div className="flex flex-wrap gap-1 items-center">
                                <Link
                                    subtle
                                    className="text-left font-semibold truncate"
                                    onClick={() => setEditingKeyId(key.id)}
                                >
                                    {String(label)}
                                </Link>
                            </div>
                        )
                    },
                },
                {
                    title: 'Status',
                    key: 'status',
                    dataIndex: 'id',
                    render: function RenderStatus(_, key) {
                        const keyDisabled = isPersonalApiKeyIdDisabled(key.id)
                        const restrictedOrgs = getRestrictedOrganizationsForKey(key.id)
                        const restrictedTeams = getRestrictedTeamsForKey(key.id)
                        const hasPartialRestrictions =
                            (restrictedOrgs.length > 0 || restrictedTeams.length > 0) && !keyDisabled

                        if (keyDisabled) {
                            const orgNames = restrictedOrgs.map((org: any) => org.name)

                            return (
                                <Tooltip
                                    title={
                                        orgNames.length === 1 ? (
                                            <span>
                                                Organization <strong>{orgNames[0]}</strong> has restricted the use of
                                                personal API keys.
                                            </span>
                                        ) : (
                                            <span>
                                                Organizations <strong>{orgNames.join(', ')}</strong> have restricted the
                                                use of personal API keys.
                                            </span>
                                        )
                                    }
                                >
                                    <LemonTag type="danger">Disabled</LemonTag>
                                </Tooltip>
                            )
                        }

                        if (hasPartialRestrictions) {
                            let tooltipMessage: JSX.Element = <span />

                            // Handle project-scoped keys with restrictions
                            if (restrictedTeams.length > 0) {
                                const restrictedTeamNames = restrictedTeams.map((team: any) => team.name)
                                const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                                if (restrictedOrgNames.length === 1 && restrictedTeamNames.length === 1) {
                                    tooltipMessage = (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys. This key will not work for project{' '}
                                            <strong>{restrictedTeamNames[0]}</strong>.
                                        </span>
                                    )
                                } else if (restrictedOrgNames.length === 1) {
                                    tooltipMessage = (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys. This key will not work for projects:{' '}
                                            <strong>{restrictedTeamNames.join(', ')}</strong>.
                                        </span>
                                    )
                                } else {
                                    // Multiple organizations affecting projects
                                    tooltipMessage = (
                                        <span>
                                            Multiple organizations have restricted personal API keys. This key will not
                                            work for projects: <strong>{restrictedTeamNames.join(', ')}</strong>.
                                        </span>
                                    )
                                }
                            }
                            // Handle organization-scoped keys with restrictions
                            else if (restrictedOrgs.length > 0) {
                                const restrictedOrgNames = restrictedOrgs.map((org: any) => org.name)

                                tooltipMessage =
                                    restrictedOrgNames.length === 1 ? (
                                        <span>
                                            Organization <strong>{restrictedOrgNames[0]}</strong> has restricted the use
                                            of personal API keys.
                                        </span>
                                    ) : (
                                        <span>
                                            Organizations <strong>{restrictedOrgNames.join(', ')}</strong> have
                                            restricted the use of personal API keys.
                                        </span>
                                    )
                            }

                            return (
                                <Tooltip title={tooltipMessage}>
                                    <LemonTag type="warning">Partial restrictions</LemonTag>
                                </Tooltip>
                            )
                        }

                        return <LemonTag type="success">Active</LemonTag>
                    },
                },
                {
                    title: 'Secret key',
                    dataIndex: 'mask_value',
                    key: 'mask_value',
                    render: (_, key) =>
                        key.mask_value ? (
                            <span className="font-mono">{key.mask_value}</span>
                        ) : (
                            <Tooltip title="This key was created before the introduction of previews" placement="right">
                                <span className="inline-flex items-center gap-1 cursor-default">
                                    <span>No preview</span>
                                    <IconInfo className="text-base" />
                                </span>
                            </Tooltip>
                        ),
                },
                {
                    title: 'Scopes',
                    key: 'scopes',
                    dataIndex: 'scopes',
                    render: function RenderValue(_, key) {
                        return key.scopes[0] === '*' ? (
                            <LemonTag type="warning">All access</LemonTag>
                        ) : (
                            <TagList tags={key.scopes} onMoreClick={() => setEditingKeyId(key.id)} />
                        )
                    },
                },
                {
                    title: 'Organization & project access',
                    key: 'access',
                    dataIndex: 'id',
                    render: function RenderValue(_, key) {
                        const restrictedOrgs = getRestrictedOrganizationsForKey(key.id)
                        const restrictedTeams = getRestrictedTeamsForKey(key.id)

                        if (key?.scoped_organizations?.length) {
                            const orgTags =
                                key.scoped_organizations?.map((id) => {
                                    const org = allOrganizations.find((org) => org.id === id)
                                    return {
                                        id,
                                        name: org?.name || '',
                                        restricted: restrictedOrgs.some((org: any) => org.id === id),
                                    }
                                }) || []

                            return (
                                <TagListWithRestrictions tags={orgTags} onMoreClick={() => setEditingKeyId(key.id)} />
                            )
                        } else if (key?.scoped_teams?.length) {
                            const teamTags =
                                key.scoped_teams?.map((id) => {
                                    const team = allTeams?.find((team) => team.id === id)
                                    return {
                                        id: String(id),
                                        name: team?.name || '',
                                        restricted: restrictedTeams.some((team: any) => team.id === id),
                                    }
                                }) || []

                            return (
                                <TagListWithRestrictions tags={teamTags} onMoreClick={() => setEditingKeyId(key.id)} />
                            )
                        }
                        return <LemonTag type="warning">All access</LemonTag>
                    },
                },
                {
                    title: 'Last Used',
                    dataIndex: 'last_used_at',
                    key: 'lastUsedAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.last_used_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A')}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    key: 'createdAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.created_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.created_at)}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: 'Last Rolled',
                    dataIndex: 'last_rolled_at',
                    key: 'lastRolledAt',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.last_rolled_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.last_rolled_at, 'MMMM DD, YYYY', 'h A')}
                            </Tooltip>
                        )
                    },
                },
                {
                    title: '',
                    key: 'actions',
                    align: 'right',
                    width: 0,
                    render: (_, key) => {
                        return (
                            <LemonMenu
                                items={[
                                    {
                                        label: 'Edit',
                                        onClick: () => setEditingKeyId(key.id),
                                    },
                                    {
                                        label: 'Roll',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Roll key "${key.label}"?`,
                                                description:
                                                    'This will generate a new key. The old key will immediately stop working.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Roll',
                                                    type: 'primary',
                                                    onClick: () => rollKey(key.id),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'secondary',
                                                },
                                            })
                                        },
                                    },
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Permanently delete key "${key.label}"?`,
                                                description:
                                                    'This action cannot be undone. Make sure to have removed the key from any live integrations first.',
                                                primaryButton: {
                                                    status: 'danger',
                                                    children: 'Permanently delete',
                                                    onClick: () => deleteKey(key.id),
                                                },
                                            })
                                        },
                                    },
                                ]}
                            >
                                <LemonButton size="small" icon={<IconEllipsis />} />
                            </LemonMenu>
                        )
                    },
                },
            ]}
        />
    )
}

export function PersonalAPIKeys(): JSX.Element {
    const { keys, canUsePersonalApiKeys } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId } = useActions(personalAPIKeysLogic)

    return (
        <>
            <p>
                These keys allow full access to your personal account through the API, as if you were logged in. You can
                also use them in integrations, such as{' '}
                <Link to="https://zapier.com/apps/posthog/">our premium Zapier one</Link>.
                <br />
                Try not to keep disused keys around. If you have any suspicion that one of these may be compromised,
                delete it and use a new one.
                <br />
                <Link to="https://posthog.com/docs/api/overview#authentication">
                    More about API authentication in PostHog Docs.
                </Link>
            </p>
            <LemonButton
                type="primary"
                icon={<IconPlus />}
                onClick={() => setEditingKeyId('new')}
                disabledReason={
                    !canUsePersonalApiKeys
                        ? 'Your organization does not allow members using personal API keys.'
                        : keys.length >= MAX_API_KEYS_PER_USER
                          ? `You can only have ${MAX_API_KEYS_PER_USER} personal API keys. Remove an existing key before creating a new one.`
                          : false
                }
            >
                Create personal API key
            </LemonButton>

            <PersonalAPIKeysTable />

            <EditKeyModal />
        </>
    )
}
