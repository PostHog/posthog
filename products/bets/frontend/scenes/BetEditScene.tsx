import { useActions, useValues } from 'kea'
import { useState } from 'react'

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
    Spinner,
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
import { BetMeasureOptions } from '../components/BetMeasureOptions'
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
        picking,
        measuredGoal,
        measureSearchLoading,
        fromBelief,
        beliefGoal,
    } = useValues(logic)
    const {
        change,
        setTitle,
        setBudget,
        selectPrimaryInsight,
        touch,
        submit,
        setPicking,
        findMeasures,
        measureFromBelief,
    } = useActions(logic)
    const goalText = (form.goal_description ?? '').trim()
    const [refining, setRefining] = useState(false)
    const beliefFirst = !picking && (fromBelief || !!beliefGoal) && !goalText
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
                                    onBlur={() => {
                                        touch('statement')
                                        measureFromBelief()
                                    }}
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
                            {(beliefFirst || (describing && !picking)) && (
                                <BetMeasureOptions
                                    id={id}
                                    onRefine={
                                        refining
                                            ? undefined
                                            : () => {
                                                  setRefining(true)
                                                  window.setTimeout(() =>
                                                      document.getElementById('bet-goal-description')?.focus()
                                                  )
                                              }
                                    }
                                />
                            )}
                            {beliefFirst && !refining ? null : (
                                <Field data-invalid={!!fieldErrors.goal_insight || undefined}>
                                    <FieldLabel htmlFor={picking ? 'bet-insight' : 'bet-goal-description'}>
                                        {picking
                                            ? 'Measure with'
                                            : describing
                                              ? 'The agent builds this measure'
                                              : beliefFirst
                                                ? 'Describe the change'
                                                : 'What should change?'}
                                    </FieldLabel>
                                    {picking ? (
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
                                                setPicking(false)
                                                window.setTimeout(() =>
                                                    document.getElementById('bet-goal-description')?.focus()
                                                )
                                            }}
                                        />
                                    ) : (
                                        <InputGroup className="Bets__goalInput">
                                            <InputGroupInput
                                                id="bet-goal-description"
                                                maxLength={500}
                                                value={form.goal_description ?? ''}
                                                aria-invalid={!!fieldErrors.goal_insight || undefined}
                                                onChange={(event) => change({ goal_description: event.target.value })}
                                                onKeyDown={(event) => {
                                                    if (event.key === 'Enter' && goalText && !describing) {
                                                        event.preventDefault()
                                                        findMeasures({ goal: goalText })
                                                    }
                                                }}
                                                onBlur={() => {
                                                    touch('goal_insight')
                                                    if (!describing && goalText && goalText !== measuredGoal) {
                                                        findMeasures({ goal: goalText })
                                                    }
                                                }}
                                                placeholder={
                                                    beliefFirst
                                                        ? 'For example: more uploaders share within a day'
                                                        : 'For example: more new teams finish setup in their first week'
                                                }
                                            />
                                            {!describing &&
                                                (measureSearchLoading || (goalText && goalText !== measuredGoal)) && (
                                                    <InputGroupAddon align="inline-end">
                                                        {measureSearchLoading ? (
                                                            <Spinner className="Bets__goalSpinner" />
                                                        ) : (
                                                            <Button
                                                                type="button"
                                                                size="sm"
                                                                variant="default"
                                                                onClick={() => findMeasures({ goal: goalText })}
                                                                data-attr="bets-form-find-measures"
                                                            >
                                                                Find measures
                                                                <kbd className="Bets__kbd">↵</kbd>
                                                            </Button>
                                                        )}
                                                    </InputGroupAddon>
                                                )}
                                        </InputGroup>
                                    )}
                                    {fieldErrors.goal_insight ? (
                                        <FieldError>{fieldErrors.goal_insight}</FieldError>
                                    ) : picking ? (
                                        <FieldDescription>
                                            {insightNote}{' '}
                                            <Button
                                                type="button"
                                                variant="link-muted"
                                                size="inline"
                                                onClick={() => setPicking(false)}
                                                data-attr="bets-form-measure-mode"
                                            >
                                                Describe it instead
                                            </Button>
                                        </FieldDescription>
                                    ) : describing ? (
                                        <FieldDescription>
                                            Edit it if you need to. The agent adds tracking when an event is missing.
                                        </FieldDescription>
                                    ) : (
                                        !measuredGoal &&
                                        !measureSearchLoading && (
                                            <FieldDescription>
                                                Write it in your own words. Bets finds the measure in your data.
                                            </FieldDescription>
                                        )
                                    )}
                                </Field>
                            )}
                            {!picking && !beliefFirst && !describing && <BetMeasureOptions id={id} />}
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
