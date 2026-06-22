import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { OnboardingStepKey } from '~/types'

import { stepKeyToTitle } from './onboardingFlowUtils'
import { onboardingLogic } from './onboardingLogic'
import { INSTALL_DEDUP_KEYS } from './types'

export function OnboardingBreadcrumbs(): JSX.Element | null {
    const { flow, currentFlowStep } = useValues(onboardingLogic)
    const { setStepId } = useActions(onboardingLogic)
    const hideBreadcrumbs = useFeatureFlag('ONBOARDING_HIDE_BREADCRUMBS', 'test')

    if (hideBreadcrumbs) {
        return null
    }

    const stepCount = flow.length
    const activeId = currentFlowStep?.id

    // Disambiguate duplicate step types by appending the product name. This keeps a
    // flow like `Install (PA) → Install (SR) → Install (WA)` readable instead of three
    // identical "Install" labels.
    const stepKeyCounts = flow.reduce<Record<string, number>>((acc, step) => {
        acc[step.stepKey] = (acc[step.stepKey] ?? 0) + 1
        return acc
    }, {})
    const labelForStep = (step: (typeof flow)[number]): string => {
        if (step.label) {
            return step.label
        }
        // The posthog-js install step is shared across products via dedup, so it gets
        // a generic "Install" label rather than being titled after whichever product
        // happens to be the dedup survivor (which would be misleading when it
        // actually installs the SDK for several products at once).
        if (step.stepKey === OnboardingStepKey.INSTALL && step.dedupKey === INSTALL_DEDUP_KEYS.POSTHOG_JS) {
            return 'Install'
        }
        const base = stepKeyToTitle(step.stepKey) ?? step.stepKey
        if (stepKeyCounts[step.stepKey] > 1) {
            const productName =
                availableOnboardingProducts[step.productKey as keyof typeof availableOnboardingProducts]?.name
            if (productName) {
                // Middle dot scopes the product name as a qualifier rather than reading
                // as one phrase ("Install · Web Analytics" instead of "Install Web Analytics").
                // Product names use the registry's Title Case ("Product Analytics",
                // "AI observability") as-is — these are proper-noun product names.
                return `${base} · ${productName}`
            }
        }
        return base
    }

    return (
        <div
            className="flex items-center justify-start gap-x-3 px-4 sm:px-2 w-full overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)] sm:[mask-image:none]"
            data-attr="onboarding-breadcrumbs"
        >
            {flow.map((step, idx) => {
                const highlightStep = step.id === activeId
                const label = labelForStep(step)
                return (
                    <React.Fragment key={`stepId-${step.id}-${idx}`}>
                        <Link
                            className={clsx('text-sm shrink-0 whitespace-nowrap', highlightStep && 'font-bold')}
                            data-text={label}
                            key={step.id}
                            onClick={() => setStepId(step.id)}
                        >
                            <span className={clsx('text-sm', !highlightStep && 'text-muted')}>{label}</span>
                        </Link>
                        {stepCount > 1 && idx !== stepCount - 1 && <IconChevronRight className="text-xl shrink-0" />}
                    </React.Fragment>
                )
            })}
        </div>
    )
}
