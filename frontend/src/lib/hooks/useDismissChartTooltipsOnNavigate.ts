import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { dismissChartTooltips } from '@posthog/quill-charts'

import { dismissInsightTooltips } from 'scenes/insights/useInsightTooltip'

/**
 * Chart tooltips render onto `document.body`, outside the scene's React tree. A scene that goes
 * away without unmounting its charts — or that unmounts them while the pointer still sits on the
 * tooltip — leaves one floating over the next page. Take both tooltip surfaces down on every
 * location change.
 */
export function useDismissChartTooltipsOnNavigate(): void {
    const { location } = useValues(router)
    const url = `${location.pathname}${location.search}${location.hash}`

    useEffect(() => {
        dismissInsightTooltips()
        dismissChartTooltips()
    }, [url])
}
