import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { IconEllipsis } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonMenu, LemonModal, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { detailedTime, humanFriendlyDetailedTime } from 'lib/utils'

import { MAX_SECRET_KEYS_PER_TEAM, TeamSecretKeyType, teamSecretKeysLogic } from './teamSecretKeysLogic'

function CreateKeyModal(): JSX.Element {
    const { editingKeyId, isEditingKeySubmitting, editingKeyChanged } = useValues(teamSecretKeysLogic)
    const { setEditingKeyId, submitEditingKey } = useActions(teamSecretKeysLogic)

    return (
        <Form logic={teamSecretKeysLogic} formKey="editingKey">
            <LemonModal
                title="Create secret key"
                onClose={() => setEditingKeyId(null)}
                isOpen={!!editingKeyId}
                width="30rem"
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
                            Create key
                        </LemonButton>
                    </>
                }
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder='For example "Production API" or "CI/CD"' maxLength={100} />
                </LemonField>
                <p className="text-muted text-sm mt-2">
                    Give your secret key a descriptive name to help you remember what it's used for.
                </p>
            </LemonModal>
        </Form>
    )
}

function TeamSecretKeysTable(): JSX.Element {
    const { keys, keysLoading } = useValues(teamSecretKeysLogic)
    const { deleteKey } = useActions(teamSecretKeysLogic)

    return (
        <LemonTable<TeamSecretKeyType>
            dataSource={keys}
            loading={keysLoading}
            loadingSkeletonRows={3}
            className="mt-4"
            nouns={['secret key', 'secret keys']}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    key: 'name',
                    render: function RenderName(name) {
                        return <span className="font-semibold">{String(name)}</span>
                    },
                },
                {
                    title: 'ID',
                    dataIndex: 'id',
                    key: 'id',
                    render: (id) => <span className="font-mono text-xs">{id}</span>,
                },
                {
                    title: 'Last used',
                    dataIndex: 'last_used_at',
                    key: 'last_used_at',
                    render: (_, key) => {
                        return key.last_used_at ? (
                            <Tooltip title={detailedTime(key.last_used_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A')}
                            </Tooltip>
                        ) : (
                            <span className="text-muted">Never</span>
                        )
                    },
                },
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    key: 'created_at',
                    render: (_, key) => {
                        return (
                            <Tooltip title={detailedTime(key.created_at)} placement="bottom">
                                {humanFriendlyDetailedTime(key.created_at)}
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
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Permanently delete key "${key.name}"?`,
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

export function TeamSecretKeys(): JSX.Element {
    const { keys } = useValues(teamSecretKeysLogic)
    const { setEditingKeyId } = useActions(teamSecretKeysLogic)

    return (
        <>
            <p>
                Secret keys allow server-side integrations and scripts to authenticate with PostHog's API. These keys
                have full access to your environment's data.
                <br />
                Keep these keys secure and don't share them publicly. If a key is compromised, delete it immediately and
                create a new one.
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
                    keys.length >= MAX_SECRET_KEYS_PER_TEAM
                        ? `You can only have ${MAX_SECRET_KEYS_PER_TEAM} secret keys per environment. Remove an existing key before creating a new one.`
                        : false
                }
            >
                Create secret key
            </LemonButton>

            <TeamSecretKeysTable />

            <CreateKeyModal />
        </>
    )
}
