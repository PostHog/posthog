import { useActions, useValues } from 'kea'

import {
    Button,
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Text,
    Textarea,
} from '@posthog/quill'

import { SceneExport } from 'scenes/sceneTypes'

import { BetsPage } from '../BetsPage'
import { BetAreaField } from '../components/BetAreaField'
import { BetEditSkeleton } from '../components/BetEditSkeleton'
import { BetFormActions } from '../components/BetFormActions'
import { BetFormSection } from '../components/BetFormSection'
import { BetFormSummary } from '../components/BetFormSummary'
import { BetGuardrailsField } from '../components/BetGuardrailsField'
import { BetInsightPicker } from '../components/BetInsightPicker'
import { BetOwnerIdeasField } from '../components/BetOwnerIdeasField'
import { BetRepositoryField } from '../components/BetRepositoryField'
import { BetTargetField } from '../components/BetTargetField'
import { money } from '../lib/format'
import { betFormLogic } from '../logics/betFormLogic'

export const scene: SceneExport = {
    component: BetEditScene,
    logic: betFormLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? 'new' }),
}

export function BetEditScene({ id = 'new' }: { id?: string }): JSX.Element {
    const logic = betFormLogic({ id })
    const {
        form,
        title,
        budget,
        error,
        existing,
        existingLoading,
        breadcrumbs,
        budgetLimitCents,
        insightOptions,
        previewNote,
        previewLoading,
        fieldErrors,
        isNew,
        describing,
    } = useValues(logic)
    const { change, setTitle, setBudget, selectPrimaryInsight, touch, submit, setDescribing } = useActions(logic)
    const insightNote = !form.goal_insight
        ? 'A saved trends insight with one series.'
        : previewLoading
          ? 'Loading the current value…'
          : previewNote
    return (
        <BetsPage
            title={isNew ? 'New bet' : 'Edit bet'}
            description={
                isNew ? 'A bet is a belief, one metric that proves it, and a budget for Bets to test ideas.' : undefined
            }
            breadcrumbs={breadcrumbs}
        >
            {existingLoading ? (
                <BetEditSkeleton />
            ) : !isNew && !existing ? (
                <Text variant="destructive">{error || 'This bet could not be loaded.'}</Text>
            ) : (
                <div className="Bets__formLayout">
                    <BetFormSummary id={id} />
                    <form
                        id="bet-form"
                        className="Bets__form"
                        noValidate
                        onSubmit={(event) => {
                            event.preventDefault()
                            submit()
                        }}
                    >
                        <BetFormSection id="bet-section-bet" title="Your bet">
                            <Field data-invalid={!!fieldErrors.statement || undefined}>
                                <FieldLabel htmlFor="bet-statement">What do you believe?</FieldLabel>
                                <Textarea
                                    id="bet-statement"
                                    autoFocus={isNew}
                                    maxLength={10000}
                                    value={form.statement}
                                    aria-invalid={!!fieldErrors.statement || undefined}
                                    onChange={(event) => change({ statement: event.target.value })}
                                    onBlur={() => touch('statement')}
                                    placeholder="Shoppers buy more when they trust the total price early, because surprise costs at the end make them leave."
                                    className="Bets__belief"
                                />
                                {fieldErrors.statement ? (
                                    <FieldError>{fieldErrors.statement}</FieldError>
                                ) : (
                                    <FieldDescription>
                                        Write a belief about your users, then why. Bets finds the changes to test.
                                    </FieldDescription>
                                )}
                            </Field>
                            <div className="Bets__formRow Bets__formRow--name">
                                <Field data-invalid={!!fieldErrors.title || undefined}>
                                    <FieldLabel htmlFor="bet-title">Name</FieldLabel>
                                    <Input
                                        id="bet-title"
                                        maxLength={160}
                                        value={title}
                                        aria-invalid={!!fieldErrors.title || undefined}
                                        onChange={(event) => setTitle(event.target.value)}
                                        onBlur={() => touch('title')}
                                        placeholder="Trust the total price early"
                                    />
                                    {fieldErrors.title ? (
                                        <FieldError>{fieldErrors.title}</FieldError>
                                    ) : (
                                        isNew && (
                                            <FieldDescription>
                                                Filled in from your belief until you change it.
                                            </FieldDescription>
                                        )
                                    )}
                                </Field>
                                <BetAreaField id={id} />
                            </div>
                        </BetFormSection>
                        <BetFormSection id="bet-section-measure" title="How we measure it">
                            <Field data-invalid={!!fieldErrors.goal_insight || undefined}>
                                <FieldLabel htmlFor={describing ? 'bet-goal-description' : 'bet-insight'}>
                                    Measure with
                                </FieldLabel>
                                {describing ? (
                                    <Textarea
                                        id="bet-goal-description"
                                        maxLength={2000}
                                        value={form.goal_description ?? ''}
                                        aria-invalid={!!fieldErrors.goal_insight || undefined}
                                        onChange={(event) => change({ goal_description: event.target.value })}
                                        onBlur={() => touch('goal_insight')}
                                        placeholder="For example: the share of new users who upload a file in their first week."
                                    />
                                ) : (
                                    <BetInsightPicker
                                        id={id}
                                        inputId="bet-insight"
                                        value={form.goal_insight ?? ''}
                                        options={insightOptions}
                                        placeholder="Choose a saved insight"
                                        invalid={!!fieldErrors.goal_insight}
                                        onSelect={(insight) => {
                                            selectPrimaryInsight(insight)
                                            window.setTimeout(() => document.getElementById('bet-target')?.focus())
                                        }}
                                        onClose={() => touch('goal_insight')}
                                        onDescribe={() => {
                                            setDescribing(true)
                                            window.setTimeout(() =>
                                                document.getElementById('bet-goal-description')?.focus()
                                            )
                                        }}
                                    />
                                )}
                                {fieldErrors.goal_insight ? (
                                    <FieldError>{fieldErrors.goal_insight}</FieldError>
                                ) : describing ? (
                                    <FieldDescription>
                                        Bets looks for a saved insight that matches, or creates one. You check it and
                                        set the target before the bet starts.{' '}
                                        <Button
                                            type="button"
                                            variant="link-muted"
                                            size="inline"
                                            onClick={() => setDescribing(false)}
                                            data-attr="bets-form-choose-insight"
                                        >
                                            Choose a saved insight instead
                                        </Button>
                                    </FieldDescription>
                                ) : (
                                    insightNote && <FieldDescription>{insightNote}</FieldDescription>
                                )}
                            </Field>
                            {form.goal_insight && !describing && <BetTargetField id={id} />}
                            <BetGuardrailsField id={id} />
                        </BetFormSection>
                        <BetFormSection id="bet-section-run" title="Run it">
                            <div className="Bets__formRow Bets__formRow--run">
                                <Field data-invalid={!!fieldErrors.budget || undefined}>
                                    <FieldLabel htmlFor="bet-budget">Budget</FieldLabel>
                                    <InputGroup className="max-w-60">
                                        <InputGroupAddon align="inline-start">
                                            <InputGroupText>$</InputGroupText>
                                        </InputGroupAddon>
                                        <InputGroupInput
                                            id="bet-budget"
                                            inputMode="decimal"
                                            autoComplete="off"
                                            value={budget}
                                            aria-invalid={!!fieldErrors.budget || undefined}
                                            onChange={(event) => setBudget(event.target.value.replace(',', '.'))}
                                            onBlur={() => touch('budget')}
                                            placeholder="20"
                                        />
                                        <InputGroupAddon align="inline-end">
                                            <InputGroupText>USD</InputGroupText>
                                        </InputGroupAddon>
                                    </InputGroup>
                                    {fieldErrors.budget ? (
                                        <FieldError>{fieldErrors.budget}</FieldError>
                                    ) : (
                                        <FieldDescription>
                                            {budgetLimitCents === null
                                                ? 'Checking the project budget…'
                                                : isNew
                                                  ? `${money(budgetLimitCents)} left in the project.`
                                                  : `Up to ${money(budgetLimitCents)}.`}
                                        </FieldDescription>
                                    )}
                                </Field>
                                <BetRepositoryField id={id} />
                            </div>
                            {isNew && <BetOwnerIdeasField />}
                        </BetFormSection>
                        <BetFormActions id={id} />
                    </form>
                </div>
            )}
        </BetsPage>
    )
}
