import { useActions, useValues } from 'kea'

import {
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
import { BetGuardrailsField } from '../components/BetGuardrailsField'
import { BetInsightPicker } from '../components/BetInsightPicker'
import { BetOwnerIdeasField } from '../components/BetOwnerIdeasField'
import { BetRepositoryField } from '../components/BetRepositoryField'
import { BetTargetField } from '../components/BetTargetField'
import { BetThesisCard } from '../components/BetThesisCard'
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
    } = useValues(logic)
    const { change, setTitle, setBudget, selectPrimaryInsight, touch, submit } = useActions(logic)
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
                    <form
                        id="bet-form"
                        className="Bets__form"
                        noValidate
                        onSubmit={(event) => {
                            event.preventDefault()
                            submit()
                        }}
                    >
                        <BetFormSection
                            id="bet-section-bet"
                            title="Your bet"
                            description="The hypothesis you want to test, in your own words."
                        >
                            <Field data-invalid={!!fieldErrors.statement || undefined}>
                                <FieldLabel htmlFor="bet-statement">What do you believe will improve?</FieldLabel>
                                <Textarea
                                    id="bet-statement"
                                    autoFocus={isNew}
                                    maxLength={10000}
                                    value={form.statement}
                                    aria-invalid={!!fieldErrors.statement || undefined}
                                    onChange={(event) => change({ statement: event.target.value })}
                                    onBlur={() => touch('statement')}
                                    placeholder="Shoppers who see the full price before checkout will finish more orders, because surprise shipping costs at the last step make them leave."
                                    className="Bets__belief"
                                />
                                {fieldErrors.statement ? (
                                    <FieldError>{fieldErrors.statement}</FieldError>
                                ) : (
                                    <FieldDescription>Write the change you expect, then why.</FieldDescription>
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
                                        placeholder="Full price before checkout"
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
                        <BetFormSection
                            id="bet-section-measure"
                            title="How we measure it"
                            description="Pick the insight that shows whether the bet worked."
                        >
                            <Field data-invalid={!!fieldErrors.goal_insight || undefined}>
                                <FieldLabel htmlFor="bet-insight">Measure with</FieldLabel>
                                <BetInsightPicker
                                    id={id}
                                    inputId="bet-insight"
                                    value={form.goal_insight}
                                    options={insightOptions}
                                    placeholder="Choose a saved insight"
                                    invalid={!!fieldErrors.goal_insight}
                                    onSelect={(insight) => {
                                        selectPrimaryInsight(insight)
                                        window.setTimeout(() => document.getElementById('bet-target')?.focus())
                                    }}
                                    onClose={() => touch('goal_insight')}
                                />
                                {fieldErrors.goal_insight ? (
                                    <FieldError>{fieldErrors.goal_insight}</FieldError>
                                ) : (
                                    insightNote && <FieldDescription>{insightNote}</FieldDescription>
                                )}
                            </Field>
                            <BetTargetField id={id} />
                            <BetGuardrailsField id={id} />
                        </BetFormSection>
                        <BetFormSection
                            id="bet-section-run"
                            title="Run it"
                            description="Set what Bets can spend and where it opens pull requests."
                        >
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
                        <BetFormActions id={id} className="Bets__formFooter" />
                    </form>
                    <div className="Bets__formAside">
                        <BetThesisCard id={id} />
                    </div>
                </div>
            )}
        </BetsPage>
    )
}
