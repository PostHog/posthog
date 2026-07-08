// The app-facing entry point for hoggie illustrations rendered by eagerly-loaded code.
//
// `@posthog/brand/hoggies` inlines each SVG into the JS bundle, and some illustrations are
// hundreds of KB each. Worse, a static import of the barrel from any module that ships with
// `AuthenticatedShell` puts the barrel on the eager path, which drags every hoggie used
// anywhere in the app (lazy scenes included) into the eager download - megabytes of SVG on
// every logged-in page load. `frontend/bin/check-eager-graph.mjs` guards against this.
//
// All app code renders hoggies from the package's PNG exports instead: each
// `@posthog/brand/hoggies/png/<name>` module is a tiny stub exporting the image URL and
// aspect ratio, so the pixels never enter the JS bundle - the browser fetches the PNG only
// when the <img> actually renders. oxlint's no-restricted-imports bans the inline-SVG
// modules repo-wide; a use case that truly needs vector output can opt out with a
// justified oxlint-disable comment.
//
//     import * as judge from '@posthog/brand/hoggies/png/judge'
//     const HedgehogJudge = pngHoggie(judge)
//     <HedgehogJudge className="w-20 h-20" />
import { ComponentType } from 'react'

import type { AssetSvgProps } from '@posthog/brand'

/** Shape of a `@posthog/brand/hoggies/png/<name>` module. */
export interface HoggiePngModule {
    src: string
    aspectRatio: number
}

/**
 * A hoggie illustration as an `<img>` backed by the package's PNG export. Drop-in for the
 * SVG barrel component: accepts the same `className`/`style`/`size`/`title` props, reserves
 * layout via the intrinsic aspect ratio, and stays decorative (`alt=""`) unless titled.
 */
export function pngHoggie({ src, aspectRatio }: HoggiePngModule): ComponentType<AssetSvgProps> {
    function HoggiePng({ className, style, size, title, width, height, ...rest }: AssetSvgProps): JSX.Element {
        // Mirror the SVG components' sizing: `size` wins, then explicit width/height, then
        // fill the container - the last only when no className is given, because inline
        // style beats utility classes (the SVG version used a width *attribute*, which
        // classes could override; an inline 100% would silently defeat w-*/h-* classes).
        const sizing =
            size != null
                ? { width: size }
                : width != null || height != null
                  ? { width, height }
                  : className
                    ? undefined
                    : { width: '100%' }
        return (
            <img
                src={src}
                alt={title ?? ''}
                className={className}
                style={{ aspectRatio: String(aspectRatio), objectFit: 'contain', ...sizing, ...style }}
                // Decorative illustrations: don't fetch until near the viewport, don't block
                // paint on decode, and never compete with real content for bandwidth.
                // (lowercase fetchpriority: React 18 only forwards the attribute un-camelized;
                // aspect-ratio above reserves layout, so lazy loading causes no shift.)
                loading="lazy"
                decoding="async"
                {...{ fetchpriority: 'low' }}
                // Callers type against the SVG prop surface; the shared subset (aria-*, data-*,
                // handlers) is valid on <img> too.
                {...(rest as React.HTMLAttributes<HTMLImageElement>)}
            />
        )
    }
    return HoggiePng
}
