import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LegacyProductSelection } from './variants/legacy/LegacyProductSelection'
import { MultiproductProductSelection } from './variants/multiproduct/MultiproductProductSelection'
import { SpotlightProductSelection } from './variants/spotlight/SpotlightProductSelection'

export function ProductSelection(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const defaultVariant = 'control'
    const variant = featureFlags[FEATURE_FLAGS.PRODUCT_SELECTION_SCREEN_VARIANT] ?? defaultVariant

    switch (variant) {
        case 'spotlight':
            return <SpotlightProductSelection />
        case 'multiproduct':
            return <MultiproductProductSelection />
        case 'control':
        default:
            return <LegacyProductSelection />
    }
}

export default ProductSelection
