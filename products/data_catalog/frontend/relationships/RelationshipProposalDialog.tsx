import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
    Textarea,
} from '@posthog/quill'

import {
    RELATIONSHIP_PROPOSAL_FIELDS,
    RELATIONSHIP_PROPOSAL_REASONING_LABEL,
    proposalDisabledReason,
} from '../relationshipProposalFields'
import { relationshipsLogic } from '../relationshipsLogic'

const FIELD_MAX_LENGTH = 400

export function RelationshipProposalDialog(): JSX.Element {
    const { proposalOpen, proposalDraft: draft, proposing } = useValues(relationshipsLogic)
    const { closeProposal, setProposalDraft, proposeRelationship } = useActions(relationshipsLogic)

    return (
        <Dialog open={proposalOpen} onOpenChange={(open: boolean) => !open && !proposing && closeProposal()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Propose a relationship</DialogTitle>
                    <DialogDescription>
                        A catalog reviewer must accept this proposal before it becomes a join available to worksheets.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        {RELATIONSHIP_PROPOSAL_FIELDS.map(([key, label]) => (
                            <Field key={key}>
                                <FieldLabel htmlFor={`data-catalog-proposal-${key}`}>{label}</FieldLabel>
                                <Input
                                    id={`data-catalog-proposal-${key}`}
                                    value={draft[key]}
                                    onChange={(event) => setProposalDraft({ [key]: event.target.value })}
                                    maxLength={FIELD_MAX_LENGTH}
                                    disabled={proposing}
                                />
                            </Field>
                        ))}
                        <Field>
                            <FieldLabel htmlFor="data-catalog-proposal-reasoning">
                                {RELATIONSHIP_PROPOSAL_REASONING_LABEL}
                            </FieldLabel>
                            <Textarea
                                id="data-catalog-proposal-reasoning"
                                value={draft.reasoning ?? ''}
                                onChange={(event) => setProposalDraft({ reasoning: event.target.value })}
                                disabled={proposing}
                            />
                        </Field>
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" disabled={proposing} onClick={() => closeProposal()}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={proposing}
                        disabledReason={proposalDisabledReason(draft)}
                        onClick={() => proposeRelationship()}
                        data-attr="data-catalog-propose-relationship"
                    >
                        Send for review
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
