// The app-facing entry point for hoggie illustrations rendered by eagerly-loaded code.
//
// `@posthog/brand/hoggies` inlines each SVG into the JS bundle, and some illustrations are
// hundreds of KB each. Worse, a static import of the barrel from any module that ships with
// `AuthenticatedShell` puts the barrel on the eager path, which drags every hoggie used
// anywhere in the app (lazy scenes included) into the eager download — megabytes of SVG on
// every logged-in page load. `frontend/bin/check-eager-graph.mjs` guards against this.
//
// Lazily-loaded scenes may import `@posthog/brand/hoggies` directly; their hoggies end up in
// their own chunks. Anything eager (layout, nav, global modals, shared components like
// ProductIntroduction) must use `lazyHoggie` instead, so the SVG loads only when it renders.
import { ComponentType, Suspense, lazy } from 'react'

import type { AssetSvgProps } from '@posthog/brand'

type Hoggies = typeof import('@posthog/brand/hoggies')
export type HoggieName = keyof Hoggies

/**
 * A hoggie illustration as a lazily-loaded component: the SVG downloads when it first
 * renders instead of shipping with the eager bundle. Drop-in for the barrel import:
 *
 *     const HedgehogJudge = lazyHoggie('HedgehogJudge')
 *     <HedgehogJudge className="w-20 h-20" />
 */
export function lazyHoggie(name: HoggieName): ComponentType<AssetSvgProps> {
    const LazyComponent = lazy(async () => {
        const hoggies = await import('@posthog/brand/hoggies')
        return { default: hoggies[name] }
    })
    return function LazyHoggie(props: AssetSvgProps): JSX.Element {
        return (
            <Suspense fallback={null}>
                <LazyComponent {...props} />
            </Suspense>
        )
    }
}
