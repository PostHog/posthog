import type { ComponentType, ReactNode } from 'react'

import type { WidgetAvailabilityConfig } from '../../widget_types/widgetAvailability'
import { useWidgetAvailability } from '../../widget_types/widgetAvailability'
import { WidgetAvailabilitySetupPrompt } from '../WidgetAvailabilitySetupPrompt/WidgetAvailabilitySetupPrompt'

export type WidgetUnavailableContentFallbackProps = {
    availability: WidgetAvailabilityConfig
}

type WidgetRuntimeAvailabilityGuardProps = {
    availability: WidgetAvailabilityConfig | undefined
    unavailableContentFallback?: ComponentType<WidgetUnavailableContentFallbackProps>
    children: ReactNode
}

/** Shows catalog-driven setup UI when a widget requirement is unmet; otherwise renders children. */
export function WidgetRuntimeAvailabilityGuard({
    availability,
    unavailableContentFallback,
    children,
}: WidgetRuntimeAvailabilityGuardProps): JSX.Element {
    const { isAvailable, config } = useWidgetAvailability(availability)

    if (isAvailable || !config) {
        return <>{children}</>
    }

    const Fallback = unavailableContentFallback ?? WidgetAvailabilitySetupPrompt
    return <Fallback availability={config} />
}
