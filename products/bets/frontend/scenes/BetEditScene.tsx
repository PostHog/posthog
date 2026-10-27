import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, FieldLabel, Input, Text, Textarea } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BetsPage } from '../BetsPage'
import { BetEditSkeleton } from '../components/BetEditSkeleton'
import { BetMetricFields } from '../components/BetMetricFields'
import { BetOwnerIdeasField } from '../components/BetOwnerIdeasField'
import { money } from '../lib/format'
import { betFormLogic } from '../logics/betFormLogic'

export const scene: SceneExport = {
    component: BetEditScene,
    logic: betFormLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? 'new' }),
}

export function BetEditScene({ id = 'new' }: { id?: string }): JSX.Element {
    const { form, busy, error, existing, existingLoading, breadcrumbs, budgetLimitCents } = useValues(
        betFormLogic({ id })
    )
    const { change, submit } = useActions(betFormLogic({ id }))
    return (
        <BetsPage title={id === 'new' ? 'New bet' : 'Edit bet'} breadcrumbs={breadcrumbs}>
            {existingLoading ? (
                <BetEditSkeleton />
            ) : id !== 'new' && !existing ? (
                <Text variant="destructive">{error || 'This bet could not be loaded.'}</Text>
            ) : (
                <form
                    className="flex max-w-170 flex-col gap-6 pt-7"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submit()
                    }}
                >
                    <Field>
                        <FieldLabel htmlFor="bet-title">Bet</FieldLabel>
                        <Input
                            id="bet-title"
                            required
                            maxLength={160}
                            value={form.title}
                            onChange={(event) => change({ title: event.target.value })}
                            placeholder="Help people find what they need"
                        />
                    </Field>
                    <Field>
                        <FieldLabel htmlFor="bet-statement">What do you believe will improve?</FieldLabel>
                        <Textarea
                            id="bet-statement"
                            required
                            value={form.statement}
                            onChange={(event) => change({ statement: event.target.value })}
                            placeholder="We believe that… because…"
                            className="min-h-28"
                        />
                    </Field>
                    <Field>
                        <FieldLabel htmlFor="bet-audience">Who is this for?</FieldLabel>
                        <Input
                            id="bet-audience"
                            value={form.audience ?? ''}
                            onChange={(event) => change({ audience: event.target.value })}
                            placeholder="For example, new workspace members"
                        />
                    </Field>
                    <BetMetricFields id={id} />
                    <div className="Bets__formRow">
                        <Field>
                            <FieldLabel htmlFor="bet-area">Product area</FieldLabel>
                            <Input
                                id="bet-area"
                                value={form.area ?? ''}
                                onChange={(event) => change({ area: event.target.value })}
                                placeholder="Search"
                            />
                        </Field>
                        <Field>
                            <FieldLabel htmlFor="bet-budget">Budget (USD)</FieldLabel>
                            <Input
                                id="bet-budget"
                                required
                                type="number"
                                min={0}
                                max={budgetLimitCents === null ? undefined : budgetLimitCents / 100}
                                step="0.01"
                                value={form.budget_cents / 100}
                                onChange={(event) =>
                                    change({ budget_cents: Math.round(Number(event.target.value) * 100) })
                                }
                            />
                            {budgetLimitCents !== null && (
                                <FieldDescription>
                                    Up to {money(budgetLimitCents)} available for this bet.
                                </FieldDescription>
                            )}
                        </Field>
                    </div>
                    {id === 'new' && <BetOwnerIdeasField />}
                    <Field>
                        <FieldLabel htmlFor="bet-repository">Repository</FieldLabel>
                        <Input
                            id="bet-repository"
                            value={form.repository ?? ''}
                            onChange={(event) => change({ repository: event.target.value })}
                            placeholder="organization/repository"
                        />
                        <FieldDescription>Use a repository connected to this PostHog project.</FieldDescription>
                    </Field>
                    {error && (
                        <Text variant="destructive" render={<p role="alert" />}>
                            {error}
                        </Text>
                    )}
                    <div className="flex flex-wrap gap-2">
                        <Button
                            variant="outline"
                            render={<LinkPrimitive to={id === 'new' ? urls.betsAll() : urls.bet(id)} />}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" variant="primary" loading={busy}>
                            {id === 'new' ? 'Create bet' : 'Save changes'}
                        </Button>
                    </div>
                </form>
            )}
        </BetsPage>
    )
}
