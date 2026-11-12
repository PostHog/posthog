import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    RELATIONSHIP_PROPOSAL_FIELDS,
    RELATIONSHIP_PROPOSAL_REASONING_LABEL,
    proposalDisabledReason,
} from '../relationshipProposalFields'
import { relationshipsLogic } from '../relationshipsLogic'

export function RelationshipProposalModal(): JSX.Element {
    const { proposalOpen, proposalDraft: draft, proposing } = useValues(relationshipsLogic)
    const { closeProposal, setProposalDraft, proposeRelationship } = useActions(relationshipsLogic)
    return (
        <LemonModal
            isOpen={proposalOpen}
            onClose={() => !proposing && closeProposal()}
            title="Propose a relationship"
            footer={
                <LemonButton
                    type="primary"
                    data-attr="data-catalog-propose-relationship"
                    onClick={proposeRelationship}
                    loading={proposing}
                    disabledReason={proposalDisabledReason(draft)}
                >
                    Send for review
                </LemonButton>
            }
        >
            <p>A catalog reviewer must accept this proposal before it becomes a join available to worksheets.</p>
            <div className="flex flex-col gap-3">
                {RELATIONSHIP_PROPOSAL_FIELDS.map(([key, label]) => (
                    <LemonField.Pure key={key} label={label}>
                        <LemonInput
                            aria-label={label}
                            value={draft[key]}
                            onChange={(value) => setProposalDraft({ [key]: value })}
                            maxLength={400}
                            disabled={proposing}
                        />
                    </LemonField.Pure>
                ))}
                <LemonField.Pure label={RELATIONSHIP_PROPOSAL_REASONING_LABEL}>
                    <LemonTextArea
                        aria-label={RELATIONSHIP_PROPOSAL_REASONING_LABEL}
                        value={draft.reasoning ?? ''}
                        disabled={proposing}
                        onChange={(reasoning) => setProposalDraft({ reasoning })}
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
