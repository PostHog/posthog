import type { ComponentType } from 'react'

import type { AssetSvgProps } from '@posthog/brand'

import type { HoggieName } from 'lib/brand/hoggies'

// Toolbar shim — the real lazyHoggie dynamically imports the whole @posthog/brand/hoggies
// barrel, and the toolbar's single-IIFE build inlines dynamic imports, which would pull
// every hoggie SVG (tens of MB) into the bundle. Decorative illustrations render nothing
// in the toolbar instead.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function lazyHoggie(_name: HoggieName): ComponentType<AssetSvgProps> {
    return function ShimmedHoggie(): null {
        return null
    }
}
