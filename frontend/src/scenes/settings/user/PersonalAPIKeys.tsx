import { LemonDialog, LemonInput, LemonLabel, LemonModal, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect } from 'react'

import { PersonalAPIKeyType } from '~/types'

import { CopyToClipboardInline } from '../../../lib/components/CopyToClipboard'
import { API_KEY_SCOPE_PRESETS, APIScopes, personalAPIKeysLogic } from './personalAPIKeysLogic'

function EditKeyModal(): JSX.Element {
    const { editingKeyId, isEditingKeySubmitting, editingKeyChanged, formScopeRadioValues } =
        useValues(personalAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey } = useActions(personalAPIKeysLogic)

    const isNew = editingKeyId === 'new'

    return (
        <Form logic={personalAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={(isNew ? 'Create a' : 'Edit your') + ' Personal API Key'}
                onClose={() => setEditingKeyId(null)}
                isOpen={!!editingKeyId}
                width="40rem"
                footer={
                    <div>
                        {isNew ? (
                            <p className="whitespace-normal -mt-2">
                                <b>WARNING:</b> For security reasons the key value <b>will only ever be shown once</b>,
                                immediately after creation.
                                <br />
                                Copy it to your destination right away.
                            </p>
                        ) : null}
                        <div className="flex flex-1 gap-2 justify-end">
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
                        </div>
                    </div>
                }
            >
                <div className="space-y-2">
                    <Field name="label" label="Label">
                        <LemonInput placeholder='for example "Zapier"' maxLength={40} />
                    </Field>

                    <LemonLabel>Scopes</LemonLabel>
                    <Field name="scopes">
                        {({ error }) => (
                            <>
                                <p>
                                    API Keys are scoped to limit what they are able to do. We highly recommend you only
                                    give the key the permissions it needs to do its job. You can add or revoke scopes
                                    later.
                                </p>
                                <div className="flex justify-between">
                                    <div className="flex-1">
                                        {error && <span className="text-danger">{error}</span>}
                                    </div>
                                    <Field name="preset">
                                        <LemonSelect
                                            placeholder="Select a preset"
                                            options={API_KEY_SCOPE_PRESETS}
                                            dropdownMatchSelectWidth={false}
                                            dropdownPlacement="bottom-end"
                                        />
                                    </Field>
                                </div>
                                <div>
                                    {APIScopes.map(({ key, actions, description }) => (
                                        <div key={key} className="flex items-center justify-between gap-2 min-h-8">
                                            <div>
                                                <b>{capitalizeFirstLetter(key.replace(/_/g, ' '))}</b>
                                            </div>
                                            <LemonRadio
                                                horizontal
                                                options={[
                                                    { label: 'No access', value: 'none' },
                                                    ...actions.map((action) => ({
                                                        label: capitalizeFirstLetter(action),
                                                        value: action,
                                                    })),
                                                ]}
                                                value={formScopeRadioValues[key] ?? 'none'}
                                                onChange={(value) => setScopeRadioValue(key, value)}
                                            />
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}
                    </Field>
                </div>
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
                    render: function RenderLabel(label, record) {
                        return (
                            <Link subtle className="font-semibold" onClick={() => setEditingKeyId(record.id)}>
                                {String(label)}
                            </Link>
                        )
                    },
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                    render: function RenderValue(value) {
                        return value ? (
                            <CopyToClipboardInline description="personal API key value">
                                {String(value)}
                            </CopyToClipboardInline>
                        ) : (
                            <i>secret</i>
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
                            <LemonButton
                                status="danger"
                                type="tertiary"
                                size="xsmall"
                                onClick={() => {
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
                                }}
                            >
                                Delete
                            </LemonButton>
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
