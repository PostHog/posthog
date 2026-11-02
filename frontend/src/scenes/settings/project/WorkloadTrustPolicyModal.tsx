import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { riskyScopeWarning } from 'lib/scopes'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function WorkloadTrustPolicyModal(): JSX.Element {
    const {
        editingPolicyId,
        editingPolicyChanged,
        isEditingPolicySubmitting,
        providers,
        scopeRows,
        scopeLevels,
        scopeSearchTerm,
    } = useValues(workloadTrustPoliciesLogic)
    const { setEditingPolicyId, submitEditingPolicy, setScopeLevel, setScopeSearchTerm } =
        useActions(workloadTrustPoliciesLogic)

    const isNew = editingPolicyId === 'new'

    return (
        <Form logic={workloadTrustPoliciesLogic} formKey="editingPolicy">
            <LemonModal
                title={isNew ? 'Add trusted workload' : 'Edit trusted workload'}
                isOpen={!!editingPolicyId}
                onClose={() => setEditingPolicyId(null)}
                width="40rem"
                hasUnsavedInput={editingPolicyChanged}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setEditingPolicyId(null)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isEditingPolicySubmitting}
                            disabledReason={!editingPolicyChanged ? 'No changes to save' : undefined}
                            onClick={submitEditingPolicy}
                            data-attr="workload-trust-policy-save"
                        >
                            {isNew ? 'Add trusted workload' : 'Save'}
                        </LemonButton>
                    </>
                }
            >
                <div className="deprecated-space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Production deploys" maxLength={200} />
                    </LemonField>
                    <LemonField name="issuer" label="CI provider">
                        <LemonSelect
                            fullWidth
                            placeholder="Choose a CI provider"
                            options={(providers?.supported ?? []).map((provider) => ({
                                value: provider.issuer,
                                label: provider.name,
                            }))}
                        />
                    </LemonField>
                    <div className="flex flex-wrap gap-4">
                        <LemonField
                            name="repository"
                            label="Repository"
                            help="The full name, for example acme/web."
                            className="flex-1 min-w-60"
                        >
                            <LemonInput placeholder="acme/web" />
                        </LemonField>
                        <LemonField
                            name="repository_id"
                            label="Repository ID"
                            help="The ID your CI provider gives the repository. It doesn't change when the repository is renamed."
                            className="flex-1 min-w-60"
                        >
                            <LemonInput placeholder="123456789" />
                        </LemonField>
                    </div>
                    <div className="flex flex-wrap gap-4">
                        <LemonField
                            name="ref"
                            label="Ref"
                            help="Leave empty to allow any ref."
                            className="flex-1 min-w-60"
                        >
                            <LemonInput placeholder="refs/heads/main" />
                        </LemonField>
                        <LemonField
                            name="environment"
                            label="Environment"
                            help="Leave empty to allow any environment."
                            className="flex-1 min-w-60"
                        >
                            <LemonInput placeholder="production" />
                        </LemonField>
                    </div>
                    <LemonField
                        name="scopes"
                        label="Scopes"
                        help="Every token from this policy gets these scopes. Scopes that would let a token outlive itself aren't available."
                    >
                        <div className="w-full">
                            <LemonInput
                                type="search"
                                placeholder="Search scopes"
                                value={scopeSearchTerm}
                                onChange={setScopeSearchTerm}
                                className="mb-2"
                                size="small"
                            />
                            <div className="max-h-[40vh] overflow-y-auto deprecated-space-y-2">
                                {scopeRows.length === 0 ? (
                                    <div className="text-secondary text-sm py-2">No scopes match your search.</div>
                                ) : (
                                    scopeRows.map(({ key, label, disabledActions }) => (
                                        <ScopeAccessRow
                                            key={key}
                                            row={{
                                                key,
                                                label,
                                                value: scopeLevels[key] ?? 'none',
                                                warning: riskyScopeWarning(
                                                    key,
                                                    scopeLevels[key] ?? 'none',
                                                    providers?.risky_scopes ?? {}
                                                ),
                                                disabledReasons: {
                                                    read: disabledActions.includes('read')
                                                        ? 'Not available for workload tokens'
                                                        : undefined,
                                                    write: disabledActions.includes('write')
                                                        ? 'Not available for workload tokens'
                                                        : undefined,
                                                },
                                            }}
                                            onChange={setScopeLevel}
                                        />
                                    ))
                                )}
                            </div>
                        </div>
                    </LemonField>
                </div>
            </LemonModal>
        </Form>
    )
}
