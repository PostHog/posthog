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
//
// Single-chunk tradeoff: all hoggies used via lazyHoggie land in one shared lazy chunk because
// `@posthog/brand` does not expose per-hoggie component subpaths (only raw SVG data via
// `./hoggies/svg/*`). The first lazyHoggie render downloads every hoggie in the barrel, but
// subsequent renders are free. Per-hoggie splitting would require building each component from
// the package's internal createSvgAsset (not exported), so this is the right tradeoff until
// upstream adds per-component subpaths.
import { ComponentType, Suspense, lazy } from 'react'

import type { AssetSvgProps } from '@posthog/brand'

type Hoggies = typeof import('@posthog/brand/hoggies')
export type HoggieName = keyof Hoggies

// Memoize one lazy component per name so that calling lazyHoggie inside a render body
// (which would otherwise mint a fresh lazy component every render and remount Suspense)
// is safe rather than just a convention.
const hoggieLazyCache = new Map<HoggieName, ComponentType<AssetSvgProps>>()

/**
 * A hoggie illustration as a lazily-loaded component: the SVG downloads when it first
 * renders instead of shipping with the eager bundle. Drop-in for the barrel import:
 *
 *     const HedgehogJudge = lazyHoggie('HedgehogJudge')
 *     <HedgehogJudge className="w-20 h-20" />
 *
 * Safe to call at module scope or inside a component — memoized per name.
 */
export function lazyHoggie(name: HoggieName): ComponentType<AssetSvgProps> {
    const cached = hoggieLazyCache.get(name)
    if (cached) {
        return cached
    }
    const LazyComponent = lazy(() =>
        import('@posthog/brand/hoggies')
            .then((hoggies) => ({ default: hoggies[name] }))
            .catch(() => ({ default: () => null }))
    )
    const LazyHoggie = function LazyHoggie(props: AssetSvgProps): JSX.Element {
        return (
            <Suspense fallback={null}>
                <LazyComponent {...props} />
            </Suspense>
        )
    }
    hoggieLazyCache.set(name, LazyHoggie)
    return LazyHoggie
}
