import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Text } from '@posthog/quill'

import { money } from '../lib/format'
import { formatMeasure } from '../lib/insightMetric'
import { betFormLogic } from '../logics/betFormLogic'

function useScrolledPast(selector: string): boolean {
    const [past, setPast] = useState(false)
    useEffect(() => {
        const element = document.querySelector(selector)
        if (!element) {
            return
        }
        const root = element.closest('main')
        const observer = new IntersectionObserver(
            ([entry]) => setPast(!entry.isIntersecting && entry.boundingClientRect.top < (entry.rootBounds?.top ?? 0)),
            { root, rootMargin: '-64px 0px 0px 0px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [selector])
    return past
}

export function BetFormSummary({ id }: { id: string }): JSX.Element {
    const { form, metricName, current, targetValue, display, budgetCents, repositories, fieldErrors, describing } =
        useValues(betFormLogic({ id }))
    const shown = useScrolledPast('#bet-statement')
    const measure = describing
        ? 'Bets finds the insight'
        : form.goal_insight && metricName
          ? `${metricName}: ${current === null ? '…' : formatMeasure(current, display)} → ${
                targetValue === null || fieldErrors.target ? 'target not set' : formatMeasure(targetValue, display)
            }`
          : 'No metric yet'
    const facts = [
        measure,
        budgetCents ? `Up to ${money(budgetCents)}` : 'No budget yet',
        repositories.join(', '),
    ].filter(Boolean)
    return (
        <div className="Bets__formSummary" data-shown={shown || undefined} aria-hidden={!shown}>
            <div className="Bets__formSummaryBar">
                <Text size="sm" className="block truncate font-medium">
                    {form.statement.trim() || 'Write what you believe will improve.'}
                </Text>
                <Text size="xs" variant="muted" className="block truncate">
                    {facts.join(' · ')}
                </Text>
            </div>
        </div>
    )
}
