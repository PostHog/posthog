import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { ProductKey } from '~/queries/schema/schema-general'

import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'

export function WelcomeCelebration({ productKey }: { productKey: ProductKey }): JSX.Element {
    const { celebratedProductKeys } = useValues(onboardingWelcomeLogic)
    const { markCelebrated } = useActions(onboardingWelcomeLogic)
    const { trigger, HogfettiComponent } = useHogfetti({ count: 60 })

    useEffect(() => {
        if (celebratedProductKeys.includes(productKey)) {
            return
        }
        markCelebrated(productKey)
        if (inStorybookTestRunner() || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        trigger()
        // Mount-only per product: the parent remounts this for each product it shows.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return <HogfettiComponent />
}
