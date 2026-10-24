import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

export function isSampleDataStatic(): boolean {
    return (
        inStorybook() ||
        inStorybookTestRunner() ||
        (typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
    )
}
