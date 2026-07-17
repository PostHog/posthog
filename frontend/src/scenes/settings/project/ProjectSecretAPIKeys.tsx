import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { APIKeyTable } from '../shared/APIKeyTable'
import { MAX_PROJECT_API_KEYS_PER_PROJECT, projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

function EditKeyModal(): JSX.Element {
    const {
        editingKey,
        editingKeyId,
        isEditingKeySubmitting,
        editingKeyChanged,
        formScopeRadioValues,
        filteredScopes,
        availablePresets,
        searchTerm,
    } = useValues(projectSecretAPIKeysLogic)
    const { setEditingKeyId, setScopeRadioValue, submitEditingKey, setSearchTerm } =
        useActions(projectSecretAPIKeysLogic)

    const isNew = editingKeyId === 'new'

    const submitDisabledReason = !editingKeyChanged
        ? 'No changes to save'
        : !editingKey.label
          ? 'Add a label'
          : !editingKey.scopes?.length
            ? 'Select at least one scope'
            : undefined

    return (
        <Form logic={projectSecretAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} project secret API key`}
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
                            disabledReason={submitDisabledReason}
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
                            options={availablePresets}
                            dropdownMatchSelectWidth={false}
                        />
                    </LemonField>
                </div>

                <p className="text-sm text-muted mb-4">
                    Project secret API keys have limited scopes. Select only the permissions needed.
                </p>

                <LemonInput
                    type="search"
                    placeholder="Search scopes..."
                    value={searchTerm}
                    onChange={setSearchTerm}
                    className="mb-2"
                    size="small"
                />

                <LemonField name="scopes">
                    <div className="max-h-[50vh] overflow-y-auto space-y-2">
                        {filteredScopes.length === 0 ? (
                            <div className="text-muted text-sm py-2">No scopes match "{searchTerm}"</div>
                        ) : (
                            filteredScopes.map(({ key, label, disabledActions }) => (
                                <ScopeAccessRow
                                    key={key}
                                    label={label}
                                    value={formScopeRadioValues[key] ?? 'none'}
                                    onChange={(value) => setScopeRadioValue(key, value)}
                                    readDisabledReason={
                                        disabledActions?.includes('read')
                                            ? 'Not available for project secret API keys'
                                            : undefined
                                    }
                                    writeDisabledReason={
                                        disabledActions?.includes('write')
                                            ? 'Not available for project secret API keys'
                                            : undefined
                                    }
                                />
                            ))
                        )}
                    </div>
                </LemonField>
            </LemonModal>
        </Form>
    )
}

export function ProjectSecretAPIKeys(): JSX.Element {
    const { keys, keysLoading } = useValues(projectSecretAPIKeysLogic)
    const { setEditingKeyId, deleteKey, rollKey } = useActions(projectSecretAPIKeysLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    return (
        <>
            <p>
                Project secret API keys allow programmatic access to a very limited set of scopes and endpoints. Unlike
                personal API keys, project secret API keys are not tied to a specific user.
            </p>
            <p className="font-bold">
                They should be kept secret as they can have scopes that allow access to the project's data.
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
                showActions={!restrictionReason}
            />

            <EditKeyModal />
        </>
    )
}
