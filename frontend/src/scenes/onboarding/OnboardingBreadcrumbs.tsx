import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { OnboardingStepKey } from '~/types'

import { onboardingLogic, stepKeyToTitle } from './onboardingLogic'

interface OnboardingBreadcrumbsProps {
    stepKey: OnboardingStepKey
    breadcrumbHighlightName?: OnboardingStepKey
}

export function OnboardingBreadcrumbs({
    stepKey,
    breadcrumbHighlightName,
}: OnboardingBreadcrumbsProps): JSX.Element | null {
    const { onboardingStepKeys } = useValues(onboardingLogic)
    const { setStepKey } = useActions(onboardingLogic)
    const hideBreadcrumbs = useFeatureFlag('ONBOARDING_HIDE_BREADCRUMBS', 'test')

    if (hideBreadcrumbs) {
        return null
    }

    const stepCount = onboardingStepKeys.length

    return (
        <div
            className="flex items-center justify-start gap-x-3 px-4 sm:px-2 w-full overflow-x-auto [mask-image:linear-gradient(to_right,black_calc(100%-24px),transparent)] sm:[mask-image:none]"
            data-attr="onboarding-breadcrumbs"
        >
            {onboardingStepKeys.map((stepName, idx) => {
                const highlightStep = [stepKey, breadcrumbHighlightName].includes(stepName)
                return (
                    <React.Fragment key={`stepKey-${idx}`}>
                        <Link
                            className={clsx('text-sm shrink-0 whitespace-nowrap', highlightStep && 'font-bold')}
                            data-text={stepKeyToTitle(stepName)}
                            key={stepName}
                            onClick={() => setStepKey(stepName)}
                        >
                            <span className={clsx('text-sm', !highlightStep && 'text-muted')}>
                                {stepKeyToTitle(stepName)}
                            </span>
                        </Link>
                        {stepCount > 1 && idx !== stepCount - 1 && <IconChevronRight className="text-xl shrink-0" />}
                    </React.Fragment>
                )
            })}
        </div>
    )
}
