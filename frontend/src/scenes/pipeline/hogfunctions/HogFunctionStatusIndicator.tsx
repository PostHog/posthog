import { LemonDropdown, LemonTag, LemonTagProps } from '@posthog/lemon-ui'

import { HogFunctionType, HogWatcherState } from '~/types'

type DisplayOptions = { tagType: LemonTagProps['type']; display: string; description: JSX.Element }
const displayMap: Record<HogWatcherState, DisplayOptions> = {
    [HogWatcherState.healthy]: {
        tagType: 'success',
        display: 'Active',
        description: <>The function is running as expected.</>,
    },
    [HogWatcherState.overflowed]: {
        tagType: 'caution',
        display: 'Degraded',
        description: (
            <>
                The function is running slow or has issues performing async requests. It has been moved to the slow lane
                and may be processing slower than usual.
            </>
        ),
    },
    [HogWatcherState.disabledForPeriod]: {
        tagType: 'danger',
        display: 'Disabled temporarily',
        description: (
            <>
                The function has been disabled temporarily due to enough slow or failed requests. It will be re-enabled
                soon.
            </>
        ),
    },
    [HogWatcherState.disabledIndefinitely]: {
        tagType: 'danger',
        display: 'Disabled',
        description: (
            <>
                The function has been disabled indefinitely due to too many slow or failed requests. Please check your
                config. Updating your function will move it back to the "degraded" state for testing. If it performs
                well, it will then be moved to the healthy.
            </>
        ),
    },
}

const DEFAULT_DISPLAY: DisplayOptions = {
    tagType: 'default',
    display: 'Unknown',
    description: (
        <>The function status is unknown. The status will be derived once enough invocations have been performed.</>
    ),
}

const DISABLED_MANUALLY_DISPLAY: DisplayOptions = {
    tagType: 'default',
    display: 'Paused',
    description: <>This function is paused</>,
}

export type HogFunctionStatusIndicatorProps = {
    hogFunction: HogFunctionType | null
}
export function HogFunctionStatusIndicator({ hogFunction }: HogFunctionStatusIndicatorProps): JSX.Element | null {
    if (!hogFunction) {
        return null
    }

    const { tagType, display, description } =
        hogFunction.type === 'site_app' || hogFunction.type === 'site_destination'
            ? hogFunction.enabled
                ? displayMap[HogWatcherState.healthy]
                : DISABLED_MANUALLY_DISPLAY
            : hogFunction.status?.state
            ? displayMap[hogFunction.status.state]
            : hogFunction.enabled
            ? DEFAULT_DISPLAY
            : DISABLED_MANUALLY_DISPLAY

    return (
        <LemonDropdown
            overlay={
                <>
                    <div className="p-2 space-y-2">
                        <h2 className="flex items-center m-0 gap-2">
                            Function status - <LemonTag type={tagType}>{display}</LemonTag>
                        </h2>

                        <p>{description}</p>
                    </div>
                </>
            }
        >
            <LemonTag type={tagType}>{display}</LemonTag>
        </LemonDropdown>
    )
}
