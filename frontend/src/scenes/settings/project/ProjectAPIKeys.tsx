import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { PROJECT_API_KEY_SCOPES, PROJECT_API_KEY_SCOPE_PRESETS } from 'lib/scopes'
import { capitalizeFirstLetter } from 'lib/utils'

import { APIKeyTable } from '../shared/APIKeyTable'
import { MAX_PROJECT_API_KEYS_PER_PROJECT, projectAPIKeysLogic } from './projectAPIKeysLogic'

function EditKeyModal(): JSX.Element {
    const { editingKeyId, isEditingKeySubmitting, editingKeyChanged, formScopeRadioValues } =
        useValues(projectAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey } = useActions(projectAPIKeysLogic)

    const isNew = editingKeyId === 'new'

    return (
        <Form logic={projectAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} project API key`}
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
                            disabledReason={!editingKeyChanged ? 'No changes to save' : undefined}
                            onClick={submitEditingKey}
                        >
                            {isNew ? 'Create key' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <LemonField name="label" label="Label">
                    <LemonInput placeholder="e.g., CI/CD Pipeline" maxLength={40} />
                </LemonField>

                <div className="flex items-center justify-between mt-4 mb-2">
                    <label className="font-semibold">Scopes</label>
                    <LemonField name="preset">
                        <LemonSelect
                            size="small"
                            placeholder="Select preset"
                            options={PROJECT_API_KEY_SCOPE_PRESETS}
                            dropdownMatchSelectWidth={false}
                        />
                    </LemonField>
                </div>

                <p className="text-sm text-muted mb-4">
                    Project API keys have limited scopes. Select only the permissions needed.
                </p>

                <LemonField name="scopes">
                    <div className="space-y-2">
                        {PROJECT_API_KEY_SCOPES.map(({ key }) => (
                            <div key={key} className="flex items-center justify-between">
                                <span className="font-medium">{capitalizeFirstLetter(key.replace(/_/g, ' '))}</span>
                                <LemonSegmentedButton
                                    value={formScopeRadioValues[key] ?? 'none'}
                                    onChange={(value) => setScopeRadioValue(key, value)}
                                    options={[
                                        { label: 'No access', value: 'none' },
                                        { label: 'Read', value: 'read' },
                                        { label: 'Write', value: 'write' },
                                    ]}
                                    size="xsmall"
                                />
                            </div>
                        ))}
                    </div>
                </LemonField>
            </LemonModal>
        </Form>
    )
}

export function ProjectAPIKeys(): JSX.Element {
    const { keys, keysLoading } = useValues(projectAPIKeysLogic)
    const { setEditingKeyId, deleteKey, rollKey } = useActions(projectAPIKeysLogic)

    return (
        <>
            <p>
                Project API keys allow programmatic access to this project's data and endpoints. They're ideal for CI/CD
                pipelines, external integrations, and automation.
            </p>
            <p className="text-sm text-muted">
                Unlike personal API keys, project keys are not tied to a specific user and have limited scopes.
            </p>

            <LemonButton
                type="primary"
                icon={<IconPlus />}
                onClick={() => setEditingKeyId('new')}
                disabledReason={
                    keys.length >= MAX_PROJECT_API_KEYS_PER_PROJECT
                        ? `Maximum ${MAX_PROJECT_API_KEYS_PER_PROJECT} keys per project`
                        : undefined
                }
            >
                Create project API key
            </LemonButton>

            <APIKeyTable
                keys={keys}
                loading={keysLoading}
                onEdit={setEditingKeyId}
                onRoll={rollKey}
                onDelete={deleteKey}
                noun="project API key"
                showCreatedBy={true}
            />

            <EditKeyModal />
        </>
    )
}
