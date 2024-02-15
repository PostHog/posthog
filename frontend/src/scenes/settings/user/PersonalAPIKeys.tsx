import {
    LemonBanner,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonMenu,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonSelectMultiple,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconEllipsis, IconErrorOutline, IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import { Fragment, useEffect } from 'react'

import { PersonalAPIKeyType } from '~/types'

import { API_KEY_SCOPE_PRESETS, APIScopes, personalAPIKeysLogic } from './personalAPIKeysLogic'

function EditKeyModal(): JSX.Element {
    const {
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        formScopeRadioValues,
        allAccessSelected,
        editingKey,
        allTeams,
        allTeamsLoading,
        allOrganizations,
    } = useValues(personalAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey, resetScopes } = useActions(personalAPIKeysLogic)

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

                    <LemonField name="access_type" className="mt-4 mb-2">
                        {({ value, onChange }) => (
                            <div className="flex items-center justify-between gap-2">
                                <LemonLabel>Organization & project access</LemonLabel>
                                <LemonSegmentedButton
                                    onChange={onChange}
                                    value={value}
                                    options={[
                                        { label: 'All-access', value: 'all' },
                                        {
                                            label: 'Organizations',
                                            value: 'organizations',
                                        },
                                        {
                                            label: 'Projects',
                                            value: 'teams',
                                        },
                                    ]}
                                    size="small"
                                />
                            </div>
                        )}
                    </LemonField>

                    {editingKey.access_type === 'all' ? (
                        <p className="mb-0">
                            This API key will allow access to all organizations and projects you're in.
                        </p>
                    ) : editingKey.access_type === 'organizations' ? (
                        <>
                            <p className="mb-2">
                                This API key will only allow access to selected organizations and all project within
                                them.
                            </p>

                            <LemonField name="scoped_organizations">
                                <LemonSelectMultiple
                                    mode="multiple"
                                    data-attr="organizations"
                                    options={
                                        allOrganizations.map((org) => ({
                                            key: `${org.id}`,
                                            label: org.name,
                                            labelComponent: (
                                                <Tooltip
                                                    title={
                                                        <div>
                                                            <div className="font-semibold">{org.name}</div>
                                                            <div className="text-xs whitespace-nowrap">
                                                                ID: {org.id}
                                                            </div>
                                                        </div>
                                                    }
                                                >
                                                    <span className="flex-1 font-semibold">{org.name}</span>
                                                </Tooltip>
                                            ),
                                        })) ?? []
                                    }
                                    placeholder="Select organizations..."
                                />
                            </LemonField>
                        </>
                    ) : editingKey.access_type === 'teams' ? (
                        <>
                            <p className="mb-2">This API key will only allow access to selected projects.</p>
                            <LemonField name="scoped_teams">
                                {({ value, onChange }) => (
                                    <LemonSelectMultiple
                                        mode="multiple"
                                        data-attr="teams"
                                        value={value.map((x: number) => String(x))}
                                        onChange={(val: string[]) => onChange(val.map((x) => parseInt(x)))}
                                        options={
                                            allTeams?.map((team) => ({
                                                key: `${team.id}`,
                                                label: team.name,
                                                labelComponent: (
                                                    <Tooltip
                                                        title={
                                                            <div>
                                                                <div className="font-semibold">{team.name}</div>
                                                                <div className="text-xs whitespace-nowrap">
                                                                    Token: {team.api_token}
                                                                </div>
                                                                <div className="text-xs whitespace-nowrap">
                                                                    Organization ID: {team.organization}
                                                                </div>
                                                            </div>
                                                        }
                                                    >
                                                        {allOrganizations.length > 1 ? (
                                                            <span>
                                                                <span>
                                                                    {
                                                                        allOrganizations.find(
                                                                            (org) => org.id === team.organization
                                                                        )?.name
                                                                    }
                                                                </span>
                                                                <span className="text-muted mx-1">/</span>
                                                                <span className="flex-1 font-semibold">
                                                                    {team.name}
                                                                </span>
                                                            </span>
                                                        ) : (
                                                            <span>{team.name}</span>
                                                        )}
                                                    </Tooltip>
                                                ),
                                            })) ?? []
                                        }
                                        loading={allTeamsLoading}
                                        placeholder="Select projects..."
                                    />
                                )}
                            </LemonField>
                        </>
                    ) : null}

                    <div className="flex items-center justify-between mt-4 mb-2">
                        <LemonLabel>Scopes</LemonLabel>
                        <LemonField name="preset">
                            <LemonSelect
                                size="small"
                                placeholder="Select preset"
                                options={API_KEY_SCOPE_PRESETS}
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
                                        {APIScopes.map(
                                            ({ key, disabledActions, warnings, disabledWhenProjectScoped }) => {
                                                const disabledDueToProjectScope =
                                                    disabledWhenProjectScoped && editingKey.access_type === 'teams'
                                                return (
                                                    <Fragment key={key}>
                                                        <div className="flex items-center justify-between gap-2 min-h-8">
                                                            <div
                                                                className={
                                                                    disabledDueToProjectScope ? 'text-muted' : undefined
                                                                }
                                                            >
                                                                <b>{capitalizeFirstLetter(key.replace(/_/g, ' '))}</b>
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
                                                            <div className="text-xs italic p-2">
                                                                {warnings[formScopeRadioValues[key]]}
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

function PersonalAPIKeysTable(): JSX.Element {
    const { keys } = useValues(personalAPIKeysLogic) as { keys: PersonalAPIKeyType[] }
    const { deleteKey, loadKeys, setEditingKeyId } = useActions(personalAPIKeysLogic)

    useEffect(() => loadKeys(), [])

    return (
        <LemonTable
            dataSource={keys}
            className="mt-4"
            columns={[
                {
                    title: 'Label',
                    dataIndex: 'label',
                    key: 'label',
                    render: function RenderLabel(label, key) {
                        return (
                            <Link
                                subtle
                                className="text-left font-semibold truncate"
                                onClick={() => setEditingKeyId(key.id)}
                            >
                                {String(label)}
                            </Link>
                        )
                    },
                },
                {
                    title: 'Scopes',
                    key: 'scopes',
                    dataIndex: 'scopes',
                    render: function RenderValue(_, key) {
                        return key.scopes[0] === '*' ? (
                            <LemonTag type="warning">(all access)</LemonTag>
                        ) : (
                            <span className="flex flex-wrap gap-1">
                                {key.scopes.slice(0, 4).map((x) => (
                                    <>
                                        <LemonTag key={x}>{x}</LemonTag>
                                    </>
                                ))}
                                {key.scopes.length > 4 && (
                                    <Tooltip title={key.scopes.slice(4).join(', ')}>
                                        <LemonTag onClick={() => setEditingKeyId(key.id)}>
                                            +{key.scopes.length - 4} more
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </span>
                        )
                    },
                },
                {
                    title: 'Last Used',
                    dataIndex: 'last_used_at',
                    key: 'lastUsedAt',
                    render: (_, key) => humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A'),
                },
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    key: 'createdAt',
                    render: (_, key) => humanFriendlyDetailedTime(key.created_at),
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
                            // <More
                            //     overlay={
                            //         <>
                            //             <LemonButton fullWidth>View</LemonButton>
                            //             <LemonButton fullWidth>Edit</LemonButton>
                            //             <LemonDivider />
                            //             <LemonButton
                            //                 status="danger"
                            //                 type="tertiary"
                            //                 size="xsmall"
                            //                 fullWidth
                            //                 onClick={() => {
                            //                     LemonDialog.open({
                            //                         title: `Permanently delete key "${key.label}"?`,
                            //                         description:
                            //                             'This action cannot be undone. Make sure to have removed the key from any live integrations first.',
                            //                         primaryButton: {
                            //                             status: 'danger',
                            //                             children: 'Permanently delete',
                            //                             onClick: () => deleteKey(key.id),
                            //                         },
                            //                     })
                            //                 }}
                            //             >
                            //                 Delete
                            //             </LemonButton>
                            //         </>
                            //     }
                            // />
                        )
                    },
                },
            ]}
        />
    )
}

export function PersonalAPIKeys(): JSX.Element {
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
            <LemonButton type="primary" icon={<IconPlus />} onClick={() => setEditingKeyId('new')}>
                Create personal API key
            </LemonButton>

            <PersonalAPIKeysTable />

            <EditKeyModal />
        </>
    )
}
