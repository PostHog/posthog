import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { type BetFormField, FIELD_LABELS } from '../lib/betForm'
import { betFormLogic } from '../logics/betFormLogic'

const FIELD_TARGETS: Record<BetFormField, string> = {
    statement: '#bet-statement',
    title: '#bet-title',
    goal_insight: '#bet-insight, #bet-goal-description',
    target: '#bet-target',
    guardrails: '.Bets__guardrail[data-undecided] button',
    budget: '#bet-budget',
    repository: '#bet-repository, .Bets__repositoryPicker button',
}

export function BetFormActions({ id }: { id: string }): JSX.Element {
    const { busy, error, errorField, missing, submitDisabledReason, isNew } = useValues(betFormLogic({ id }))
    const { reveal } = useActions(betFormLogic({ id }))
    const focusField = (field: BetFormField): void => {
        reveal(field)
        document.querySelector<HTMLElement>(FIELD_TARGETS[field])?.focus()
    }
    return (
        <div className="Bets__formActions">
            {error && (
                <Text variant="destructive" size="xs" render={<p role="alert" className="m-0" />}>
                    {errorField ? (
                        <>
                            Check the{' '}
                            <Button type="button" variant="link" size="inline" onClick={() => focusField(errorField)}>
                                {FIELD_LABELS[errorField]}
                            </Button>{' '}
                            and try again.
                        </>
                    ) : (
                        error
                    )}
                </Text>
            )}
            <div className="flex flex-wrap gap-2">
                <Button
                    type="submit"
                    form="bet-form"
                    variant="primary"
                    loading={busy}
                    disabledReason={submitDisabledReason ?? undefined}
                    data-attr={isNew ? 'bets-form-create' : 'bets-form-save'}
                >
                    {isNew ? 'Create bet' : 'Save changes'}
                </Button>
                <Button variant="outline" render={<LinkPrimitive to={isNew ? urls.betsAll() : urls.bet(id)} />}>
                    Cancel
                </Button>
            </div>
            {missing.length > 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Still needed:{' '}
                    {missing.map((part, index) => (
                        <span key={part.field}>
                            <Button
                                type="button"
                                variant="link-muted"
                                size="inline"
                                onClick={() => focusField(part.field)}
                            >
                                {part.label}
                            </Button>
                            {index < missing.length - 1 ? ', ' : '.'}
                        </span>
                    ))}
                </Text>
            ) : (
                submitDisabledReason && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {submitDisabledReason}
                    </Text>
                )
            )}
        </div>
    )
}
