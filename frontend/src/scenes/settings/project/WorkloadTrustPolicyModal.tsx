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
        editingPolicy,
        editingProvider,
        conditionFields,
        claimLabels,
    } = useValues(workloadTrustPoliciesLogic)
    const { setEditingPolicyId, submitEditingPolicy, setScopeLevel, setScopeSearchTerm, setConditionValue } =
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
                    <LemonField name="issuer" label="Provider">
                        <LemonSelect
                            fullWidth
                            placeholder="Choose a provider"
                            options={(providers?.supported ?? []).map((provider) => ({
                                value: provider.issuer,
                                label: provider.name,
                            }))}
                        />
                    </LemonField>
                    <div className="flex flex-wrap gap-4">
                        <LemonField
                            name="subject_name"
                            label={claimLabels.subjectName}
                            help={editingProvider?.subject_name_claim.help_text || undefined}
                            className="flex-1 min-w-60"
                        >
                            <LemonInput />
                        </LemonField>
                        <LemonField
                            name="subject"
                            label={claimLabels.subject}
                            help={editingProvider?.subject_claim.help_text || undefined}
                            className="flex-1 min-w-60"
                        >
                            <LemonInput />
                        </LemonField>
                    </div>
                    {conditionFields.length > 0 ? (
                        <LemonField
                            name="conditions"
                            label="Conditions"
                            help="A token matches only when it carries every value you set. Leave a field empty to allow any value."
                        >
                            {() => (
                                <div className="flex flex-wrap gap-4 w-full">
                                    {conditionFields.map((claim) => (
                                        <LemonField.Pure
                                            key={claim.name}
                                            label={claim.label}
                                            help={claim.helpText || undefined}
                                            className="flex-1 min-w-60"
                                        >
                                            <LemonInput
                                                value={editingPolicy.conditions[claim.name] ?? ''}
                                                onChange={(value) => setConditionValue(claim.name, value)}
                                                data-attr={`workload-trust-policy-condition-${claim.name}`}
                                            />
                                        </LemonField.Pure>
                                    ))}
                                </div>
                            )}
                        </LemonField>
                    ) : null}
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
