import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import type { ScopeAccessLevel } from 'lib/scopes'

import { APIKeyTable } from '../shared/APIKeyTable'
import { GatewayKeySpend } from './GatewayKeySpend'
import { MAX_PROJECT_API_KEYS_PER_PROJECT, projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'
import { QuillEditKeyDialog } from './QuillEditKeyDialog'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isNew = editingKeyId === 'new'

    const submitDisabledReason = !editingKeyChanged
        ? 'No changes to save'
        : !editingKey.label
          ? 'Add a label'
          : !editingKey.scopes?.length
            ? 'Select at least one scope'
            : undefined

    const closeModal = (): void => setEditingKeyId(null)
    const renderScopeRow = ({ key, label, info, disabledActions }: (typeof filteredScopes)[number]): JSX.Element => {
        const disabledReason = (action: 'read' | 'write'): string | undefined =>
            disabledActions?.includes(action) ? 'Not available for project secret API keys' : undefined
        return (
            <ScopeAccessRow
                key={key}
                row={{
                    key,
                    label,
                    info,
                    value: (formScopeRadioValues[key] ?? 'none') as ScopeAccessLevel,
                    disabledReasons: {
                        read: disabledReason('read'),
                        write: disabledReason('write'),
                    },
                }}
                onChange={setScopeRadioValue}
            />
        )
    }

    if (todayRailNav) {
        return (
            <QuillEditKeyDialog
                isNew={isNew}
                isOpen={!!editingKeyId}
                onClose={closeModal}
                hasUnsavedInput={editingKeyChanged}
                isSubmitting={isEditingKeySubmitting}
                submitDisabledReason={submitDisabledReason}
                onSubmit={submitEditingKey}
                availablePresets={availablePresets}
                searchTerm={searchTerm}
                onSearchTermChange={setSearchTerm}
                scopeRows={filteredScopes.map(renderScopeRow)}
            />
        )
    }

    return (
        <Form logic={projectSecretAPIKeysLogic} formKey="editingKey">
            <LemonModal
                title={`${isNew ? 'Create' : 'Edit'} project secret API key`}
                onClose={closeModal}
                isOpen={!!editingKeyId}
                width="40rem"
                hasUnsavedInput={editingKeyChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeModal}>
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
                            filteredScopes.map(renderScopeRow)
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const openNewKey = (): void => setEditingKeyId('new')
    const createDisabledReason =
        keys.length >= MAX_PROJECT_API_KEYS_PER_PROJECT
            ? `Maximum ${MAX_PROJECT_API_KEYS_PER_PROJECT} keys per project`
            : undefined
    const keyTable = (
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
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <Text size="xs" render={<p className="m-0" />}>
                    Project secret API keys allow programmatic access to a very limited set of scopes and endpoints.
                    Unlike personal API keys, project secret API keys are not tied to a specific user.
                </Text>
                <Text size="xs" weight="semibold" render={<p className="m-0" />}>
                    They should be kept secret as they can have scopes that allow access to the project's data.
                </Text>
                {!restrictionReason && (
                    <div>
                        <Button variant="primary" onClick={openNewKey} disabledReason={createDisabledReason}>
                            <IconPlus />
                            Create project secret API key
                        </Button>
                    </div>
                )}
                {keyTable}
                <GatewayKeySpend />
                <EditKeyModal />
            </div>
        )
    }

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
                    onClick={openNewKey}
                    disabledReason={createDisabledReason}
                >
                    Create project secret API key
                </LemonButton>
            )}

            {keyTable}

            <GatewayKeySpend />

            <EditKeyModal />
        </>
    )
}
