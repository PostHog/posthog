import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { MAX_OWNER_IDEAS, betFormLogic } from '../logics/betFormLogic'

export function BetOwnerIdeasField(): JSX.Element {
    const { ownerIdeas } = useValues(betFormLogic({ id: 'new' }))
    const { addOwnerIdea, changeOwnerIdea, removeOwnerIdea } = useActions(betFormLogic({ id: 'new' }))
    const removable = ownerIdeas.length > 1 || !!ownerIdeas[0]
    return (
        <Field>
            <FieldLabel htmlFor="bet-idea-0">Your ideas (optional)</FieldLabel>
            <div className="flex flex-col gap-2">
                {ownerIdeas.map((idea, index) => (
                    <div key={index} className="flex items-center gap-2">
                        <Input
                            id={`bet-idea-${index}`}
                            maxLength={255}
                            value={idea}
                            autoFocus={index > 0 && index === ownerIdeas.length - 1 && !idea}
                            onChange={(event) => changeOwnerIdea(index, event.target.value)}
                            placeholder="Describe a change you want to test"
                            aria-label={index ? `Idea ${index + 1}` : undefined}
                        />
                        {removable && (
                            <Button
                                type="button"
                                size="icon"
                                variant="default"
                                aria-label="Remove idea"
                                tooltip="Remove idea"
                                onClick={() => removeOwnerIdea(index)}
                                data-attr="bets-form-remove-idea"
                            >
                                <IconX />
                            </Button>
                        )}
                    </div>
                ))}
            </div>
            {ownerIdeas.length < MAX_OWNER_IDEAS && (
                <div>
                    <Button
                        type="button"
                        variant="outline"
                        disabledReason={ownerIdeas.at(-1)?.trim() ? undefined : 'Fill in the last idea first.'}
                        onClick={addOwnerIdea}
                        data-attr="bets-form-add-idea"
                    >
                        <IconPlus />
                        Add another idea
                    </Button>
                </div>
            )}
            <FieldDescription>
                The Scout checks each idea against your data. Nothing is built until you choose an idea.
            </FieldDescription>
        </Field>
    )
}
