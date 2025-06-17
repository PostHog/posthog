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
                config. Updating your function will re-enable it.
            </>
        ),
    },
}

const DEFAULT_DISPLAY: DisplayOptions = {
    tagType: 'success',
    display: 'Active',
    description: (
        <>
            The function is enabled but the function status is unknown. The status will be derived once enough
            invocations have been performed.
        </>
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

    const { tagType, display, description } = !hogFunction.enabled
        ? DISABLED_MANUALLY_DISPLAY
        : hogFunction.status?.state
        ? displayMap[hogFunction.status.state]
        : DEFAULT_DISPLAY

    return (
        <LemonDropdown
            overlay={
                <>
                    <div className="p-2 deprecated-space-y-2 max-w-120">
                        <h2 className="flex gap-2 items-center m-0">
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
