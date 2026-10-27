import type { Decorator } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'

declare module 'storybook/internal/types' {
    interface Parameters {
        pageUrl?: string
    }
}

/** Global story decorator that allows setting the page URL.
 *
 * ```ts
 * export default {
 *   title: 'My story',
 *   component: MyComponent,
 *   parameters: {
 *     pageUrl: urls.heatmaps(),
 *   },
 * } as ComponentMeta<typeof MyComponent>
 * ```
 */
export const withPageUrl: Decorator = (Story, { parameters: { pageUrl } }) => {
    const Component = ({ pageUrl }: { pageUrl: string }): JSX.Element | null => {
        useEffect(() => {
            if (pageUrl) {
                // withKea mounts the router in an effect of a child component. React runs child
                // effects first, Redact runs parent effects first, so wait until all effects ran.
                queueMicrotask(() => router.actions.push(pageUrl))
            }
        }, [pageUrl])

        return <Story />
    }

    return <Component pageUrl={pageUrl} />
}
