import { useValues } from 'kea'
import { useEffect } from 'react'
import { breadcrumbsLogic } from './breadcrumbsLogic'

/** Syncs page title with scene breadcrumbs. */
export function usePageTitle(): void {
    const { sceneBreadcrumbs } = useValues(breadcrumbsLogic)

    useEffect(() => {
        const reverseBreadcrumbNames = sceneBreadcrumbs
            .filter((breadcrumb) => !!breadcrumb.name)
            .map((breadcrumb) => breadcrumb.name as string)
            .reverse()
        reverseBreadcrumbNames.push('PostHog')
        document.title = reverseBreadcrumbNames.join(' • ')
    }, [sceneBreadcrumbs])
}
