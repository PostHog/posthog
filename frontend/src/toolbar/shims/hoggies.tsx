import type { ComponentType } from 'react'

import type { AssetSvgProps } from '@posthog/brand'

import type { HoggiePngModule } from 'lib/brand/hoggies'

// Toolbar shim — hoggie illustrations are decorative, and the toolbar runs on customer
// sites where every extra asset request (and CSP entry) counts, so they render nothing
// in the toolbar instead.
export function pngHoggie(_module: HoggiePngModule): ComponentType<AssetSvgProps> {
    return function ShimmedHoggie(): null {
        return null
    }
}
