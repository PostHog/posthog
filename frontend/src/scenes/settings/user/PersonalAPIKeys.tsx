import {
    LemonBanner,
    LemonDialog,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { capitalizeFirstLetter, humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect } from 'react'

import { PersonalAPIKeyType } from '~/types'

import { API_KEY_SCOPE_PRESETS, APIScopes, personalAPIKeysLogic } from './personalAPIKeysLogic'

function EditKeyModal(): JSX.Element {
    const { editingKeyId, isEditingKeySubmitting, editingKeyChanged, formScopeRadioValues, allAccessSelected } =
        useValues(personalAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey, resetScopes } = useActions(personalAPIKeysLogic)

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
                                        {APIScopes.map(({ key, actions }) => (
                                            <div key={key} className="flex items-center justify-between gap-2 min-h-8">
                                                <div>
                                                    <b>{capitalizeFirstLetter(key.replace(/_/g, ' '))}</b>
                                                </div>
                                                <LemonSegmentedButton
                                                    onChange={(value) => setScopeRadioValue(key, value)}
                                                    value={formScopeRadioValues[key] ?? 'none'}
                                                    options={[
                                                        { label: 'No access', value: 'none' },
                                                        ...actions.map((action) => ({
                                                            label: capitalizeFirstLetter(action),
                                                            value: action,
                                                        })),
                                                    ]}
                                                    size="xsmall"
                                                />
                                            </div>
                                        ))}
                                    </div>
                                )}
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
                                    <LemonTag onClick={() => setEditingKeyId(key.id)}>
                                        +{key.scopes.length - 4} more
                                    </LemonTag>
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
