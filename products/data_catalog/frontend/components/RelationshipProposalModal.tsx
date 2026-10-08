import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { relationshipsLogic } from '../relationshipsLogic'

const FIELDS = [
    ['source_table_name', 'Source table'],
    ['source_table_key', 'Source key'],
    ['joining_table_name', 'Related table'],
    ['joining_table_key', 'Related key'],
    ['field_name', 'Relationship name'],
] as const

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
                    onClick={proposeRelationship}
                    loading={proposing}
                    disabledReason={
                        FIELDS.some(([key]) => !draft[key].trim())
                            ? 'Fill in both tables, keys, and a relationship name'
                            : undefined
                    }
                >
                    Send for review
                </LemonButton>
            }
        >
            <p>A catalog reviewer must accept this proposal before it becomes a join available to worksheets.</p>
            <div className="flex flex-col gap-3">
                {FIELDS.map(([key, label]) => (
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
                <LemonField.Pure label="Why should these tables be related?">
                    <LemonTextArea
                        aria-label="Why should these tables be related?"
                        value={draft.reasoning ?? ''}
                        disabled={proposing}
                        onChange={(reasoning) => setProposalDraft({ reasoning })}
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
