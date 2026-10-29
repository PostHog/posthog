import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { Button, Field, FieldDescription, FieldTitle, Input } from '@posthog/quill'

import { MAX_OWNER_IDEAS } from '../lib/betForm'
import { betFormLogic } from '../logics/betFormLogic'

export function BetOwnerIdeasField(): JSX.Element {
    const { ownerIdeas } = useValues(betFormLogic({ id: 'new' }))
    const { addOwnerIdea, changeOwnerIdea, removeOwnerIdea } = useActions(betFormLogic({ id: 'new' }))
    const lastEmpty = ownerIdeas.length > 0 && !ownerIdeas.at(-1)?.trim()
    return (
        <Field>
            <FieldTitle>Your ideas (optional)</FieldTitle>
            <FieldDescription>
                Have an idea already? The Scout checks it against your data, next to its own ideas.
            </FieldDescription>
            {ownerIdeas.length > 0 && (
                <ol className="m-0 flex list-none flex-col gap-2 p-0">
                    {ownerIdeas.map((idea, index) => (
                        <li key={index} className="flex items-center gap-2">
                            <Input
                                id={`bet-idea-${index}`}
                                maxLength={255}
                                value={idea}
                                autoFocus={index === ownerIdeas.length - 1 && !idea}
                                onChange={(event) => changeOwnerIdea(index, event.target.value)}
                                placeholder="For example, show shipping costs on the product page"
                                aria-label={`Idea ${index + 1}`}
                            />
                            <Button
                                type="button"
                                size="icon"
                                variant="default"
                                aria-label={`Remove idea ${index + 1}`}
                                tooltip="Remove idea"
                                onClick={() => removeOwnerIdea(index)}
                                data-attr="bets-form-remove-idea"
                            >
                                <IconX />
                            </Button>
                        </li>
                    ))}
                </ol>
            )}
            {ownerIdeas.length < MAX_OWNER_IDEAS && (
                <div>
                    <Button
                        type="button"
                        variant="outline"
                        disabledReason={lastEmpty ? 'Fill in this idea first.' : undefined}
                        onClick={addOwnerIdea}
                        data-attr="bets-form-add-idea"
                    >
                        <IconPlus />
                        {ownerIdeas.length ? 'Add another idea' : 'Add an idea'}
                    </Button>
                </div>
            )}
        </Field>
    )
}
