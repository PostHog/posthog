import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { QuillWorkloadSubjectFields } from './QuillWorkloadSubjectFields'
import { subjectLookupBlocked } from './workloadConditionPresets'
import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function WorkloadSubjectFields(): JSX.Element {
    const { editingPolicy, editingProvider, claimLabels, subjectLookup, subjectLookupLoading, subjectLookupError } =
        useValues(workloadTrustPoliciesLogic)
    const { lookUpSubject } = useActions(workloadTrustPoliciesLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const canLookUp = !!editingProvider?.can_resolve_subject
    const lookupBlocked = subjectLookupBlocked(editingPolicy.conditions, editingProvider)
    const found = subjectLookup && subjectLookup.subject === editingPolicy.subject ? subjectLookup : null
    const onPressEnter = canLookUp && !lookupBlocked && !subjectLookupLoading ? lookUpSubject : undefined
    const lookUpDisabledReason =
        lookupBlocked ??
        (!editingPolicy.subject_name.trim() ? `Enter the ${claimLabels.subjectName.toLowerCase()} first` : undefined)
    const subjectHelp = found
        ? `Found through ${found.found_via}.`
        : subjectLookupError
          ? `${subjectLookupError} You can enter it by hand.`
          : editingProvider?.subject_claim.help_text || undefined

    if (todayRailNav) {
        return (
            <QuillWorkloadSubjectFields
                subjectNameLabel={claimLabels.subjectName}
                subjectNameHelp={editingProvider?.subject_name_claim.help_text || undefined}
                subjectNamePlaceholder={editingProvider?.subject_name_claim.placeholder || undefined}
                subjectLabel={claimLabels.subject}
                subjectHelp={subjectHelp}
                subjectPlaceholder={editingProvider?.subject_claim.placeholder || undefined}
                canLookUp={canLookUp}
                onLookUp={lookUpSubject}
                onPressEnter={onPressEnter}
                lookUpLoading={subjectLookupLoading}
                lookUpDisabledReason={lookUpDisabledReason}
            />
        )
    }

    return (
        <>
            <LemonField
                name="subject_name"
                label={claimLabels.subjectName}
                help={editingProvider?.subject_name_claim.help_text || undefined}
            >
                {({ value, onChange }) => (
                    <div className="flex gap-2 w-full">
                        <LemonInput
                            value={value}
                            onChange={onChange}
                            onPressEnter={onPressEnter}
                            placeholder={editingProvider?.subject_name_claim.placeholder || undefined}
                            className="flex-1"
                            data-attr="workload-trust-policy-subject-name"
                        />
                        {canLookUp ? (
                            <LemonButton
                                type="secondary"
                                icon={<IconSearch />}
                                onClick={lookUpSubject}
                                loading={subjectLookupLoading}
                                disabledReason={lookUpDisabledReason}
                                data-attr="workload-trust-policy-look-up-subject"
                            >
                                Look up
                            </LemonButton>
                        ) : null}
                    </div>
                )}
            </LemonField>
            <LemonField name="subject" label={claimLabels.subject} help={subjectHelp}>
                <LemonInput
                    placeholder={editingProvider?.subject_claim.placeholder || undefined}
                    data-attr="workload-trust-policy-subject"
                />
            </LemonField>
        </>
    )
}
