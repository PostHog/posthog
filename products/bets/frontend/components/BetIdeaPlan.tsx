import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Input, Text } from '@posthog/quill'

import type { BetsDetailApi, BetsWorkApi } from '../generated/api.schemas'
import type { PlanField } from '../lib/plan'
import { betLogic } from '../logics/betLogic'

const FIELDS: Record<PlanField, { label: string; step: string; min: number; className: string }> = {
    days: { label: 'Days to run', step: '1', min: 2, className: 'Bets__planInput' },
    mde: { label: 'Smallest change to find, in percent', step: '0.1', min: 0.1, className: 'Bets__planInput' },
    audience: { label: 'People a day', step: '1', min: 1, className: 'Bets__planInput Bets__planInput--wide' },
}

export function BetIdeaPlan({ item, bet }: { item: BetsWorkApi; bet: BetsDetailApi }): JSX.Element | null {
    const { ideaPlans, busyOperation } = useValues(betLogic({ id: bet.id }))
    const { editPlan } = useActions(betLogic({ id: bet.id }))
    const plan = ideaPlans[item.id]
    if (!plan) {
        return null
    }
    const editable = bet.is_owner && busyOperation !== `work:${item.id}:build`
    const field = (name: PlanField): JSX.Element => (
        <Input
            size="sm"
            type="number"
            inputMode={name === 'mde' ? 'decimal' : 'numeric'}
            min={FIELDS[name].min}
            step={FIELDS[name].step}
            aria-label={FIELDS[name].label}
            placeholder={name === 'audience' ? 'How many?' : '?'}
            className={FIELDS[name].className}
            value={plan.draft[name]}
            disabled={!editable}
            onChange={(event) => editPlan(item.id, item.plan, name, event.target.value)}
            data-attr={`bets-plan-${name}`}
        />
    )
    const notes = [
        ...(plan.audienceMissing && bet.is_owner
            ? ['Bets does not know how many people see this change. Enter a daily number to plan the run.']
            : []),
        ...plan.warnings,
    ]
    return (
        <div className="Bets__plan flex min-w-0 flex-col gap-1.5" data-attr="bets-idea-plan">
            <p className="Bets__planSentence m-0">
                <span className="whitespace-nowrap">Run for {field('days')} days</span>{' '}
                <span className="whitespace-nowrap">to find a change of {field('mde')}% or more,</span>{' '}
                <span className="whitespace-nowrap">from {field('audience')} people a day.</span>
            </p>
            {notes.map((note) => (
                <Text key={note} size="xs" variant="muted" render={<p className="m-0 flex items-start gap-1.5" />}>
                    <IconInfo className="Bets__planNoteIcon shrink-0" aria-hidden />
                    {note}
                </Text>
            ))}
        </div>
    )
}
