import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldLabel, Input } from '@posthog/quill'

import { betLogic } from '../logics/betLogic'

export function BetAddIdeaForm({ betId }: { betId: string }): JSX.Element {
    const { busy, busyOperation, ideaDraft } = useValues(betLogic({ id: betId }))
    const { addIdea, setAddingIdea, setIdeaDraft } = useActions(betLogic({ id: betId }))
    const adding = busyOperation === 'add-idea'
    return (
        <div className="px-0 pt-3 pb-1" data-attr="bets-add-idea-form">
            <form
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (ideaDraft.trim()) {
                        addIdea(ideaDraft)
                    }
                }}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        setAddingIdea(false)
                    }
                }}
            >
                <Field>
                    <FieldLabel htmlFor="bets-add-idea">Your idea</FieldLabel>
                    <Input
                        id="bets-add-idea"
                        autoFocus
                        maxLength={255}
                        value={ideaDraft}
                        onChange={(event) => setIdeaDraft(event.target.value)}
                        placeholder="Describe a change you want to test"
                    />
                    <FieldDescription>The Scout checks it against your data before you choose.</FieldDescription>
                </Field>
                <div className="flex flex-wrap items-center gap-2">
                    <Button
                        type="submit"
                        variant="primary"
                        loading={adding}
                        disabled={busy && !adding}
                        disabledReason={ideaDraft.trim() ? undefined : 'Describe the idea first.'}
                        data-attr="bets-add-idea-submit"
                    >
                        Add idea
                    </Button>
                    <Button
                        type="button"
                        variant="link-muted"
                        disabled={adding}
                        onClick={() => setAddingIdea(false)}
                        data-attr="bets-add-idea-cancel"
                    >
                        Cancel
                    </Button>
                </div>
            </form>
        </div>
    )
}
