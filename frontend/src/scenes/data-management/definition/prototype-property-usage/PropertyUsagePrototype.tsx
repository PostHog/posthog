// PROTOTYPE — throwaway. Four variants of a usage section on the property definition page, switchable via
// `?variant=A|B|C|D`, with mock data picked by `?scenario=heavy|light|dead`. Question: what usage details make
// a property's page useful for taxonomy cleanup? Stacked on PR 82610, which tracks 30-day property query usage.
import { PrototypeSwitcher, usePrototypeParam } from 'lib/components/PrototypeSwitcher/PrototypeSwitcher'

import { USAGE_SCENARIOS, getMockPropertyUsage } from './propertyUsageMock'
import { VARIANT_A_NAME, VariantA } from './VariantA'
import { VARIANT_B_NAME, VariantB } from './VariantB'
import { VARIANT_C_NAME, VariantC } from './VariantC'
import { VARIANT_D_NAME, VariantD } from './VariantD'

const VARIANTS = [
    { key: 'A', name: VARIANT_A_NAME },
    { key: 'B', name: VARIANT_B_NAME },
    { key: 'C', name: VARIANT_C_NAME },
    { key: 'D', name: VARIANT_D_NAME },
]

export function PropertyUsagePrototype(): JSX.Element {
    const variant = usePrototypeParam('variant', 'A')
    const usage = getMockPropertyUsage(usePrototypeParam('scenario', 'heavy'))

    return (
        <>
            {variant === 'A' && <VariantA usage={usage} />}
            {variant === 'B' && <VariantB usage={usage} />}
            {variant === 'C' && <VariantC usage={usage} />}
            {variant === 'D' && <VariantD usage={usage} />}
            <PrototypeSwitcher
                variants={VARIANTS}
                extra={[{ param: 'scenario', label: 'Data', options: USAGE_SCENARIOS }]}
            />
        </>
    )
}
