import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { PROJECT_SECRET_API_KEY_SCOPES, PROJECT_SECRET_API_KEY_SCOPE_PRESETS } from 'lib/scopes'
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
                            options={PROJECT_SECRET_API_KEY_SCOPE_PRESETS}
                            dropdownMatchSelectWidth={false}
                        />
                    </LemonField>
                </div>

                <p className="text-sm text-muted mb-4">
                    Project API keys have limited scopes. Select only the permissions needed.
                </p>

                <LemonField name="scopes">
                    <div className="space-y-2">
                        {PROJECT_SECRET_API_KEY_SCOPES.map(({ key, disabledActions }) => (
                            <div key={key} className="flex items-center justify-between">
                                <span className="font-medium">{capitalizeFirstLetter(key.replace(/_/g, ' '))}</span>
                                <LemonSegmentedButton
                                    value={formScopeRadioValues[key] ?? 'none'}
                                    onChange={(value) => setScopeRadioValue(key, value)}
                                    options={[
                                        { label: 'No access', value: 'none' },
                                        {
                                            label: 'Read',
                                            value: 'read',
                                            disabledReason: disabledActions?.includes('read')
                                                ? 'Not available for project secret API keys'
                                                : undefined,
                                        },
                                        {
                                            label: 'Write',
                                            value: 'write',
                                            disabledReason: disabledActions?.includes('write')
                                                ? 'Not available for project secret API keys'
                                                : undefined,
                                        },
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

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    return (
        <>
            <p>
                Project secret API keys allow programmatic access a very limited set of endpoints. Unlike personal API
                keys, project secret API keys are not tied to a specific user and have limited scopes.
            </p>
            <p className="font-bold">
                They should be kept secret as they can have scopes that allow to the project's data.
            </p>

            {!restrictionReason && (
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
                    Create project secret API key
                </LemonButton>
            )}

            <APIKeyTable
                keys={keys}
                loading={keysLoading}
                onEdit={setEditingKeyId}
                onRoll={rollKey}
                onDelete={deleteKey}
                noun="project secret API key"
                showCreatedBy={true}
                actionsDisabled={restrictionReason === null}
            />

            <EditKeyModal />
        </>
    )
}
