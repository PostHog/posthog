import { LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

export interface SelfDrivingSignalSourceToggleProps {
    /** Signal source product, named as it is in the inbox signal sources modal. */
    sourceName: string
    /** What this source emits, e.g. "evaluation report". */
    signalNoun: string
    /** `null` while the signal source configs are still loading. */
    enabled: boolean | null
    toggling: boolean
    onChange: () => void
    'data-attr': string
}

export function SelfDrivingSignalSourceToggle({
    sourceName,
    signalNoun,
    enabled,
    toggling,
    onChange,
    'data-attr': dataAttr,
}: SelfDrivingSignalSourceToggleProps): JSX.Element {
    if (enabled === null) {
        return <LemonSkeleton className="h-5 w-72 rounded" />
    }

    return (
        <LemonSwitch
            size="small"
            checked={enabled}
            onChange={onChange}
            loading={toggling}
            label={
                <span className="flex flex-wrap items-baseline gap-1">
                    <span>{sourceName} signal source</span>
                    <span className="text-xs font-normal text-muted">Must be on to accept {signalNoun} signals.</span>
                </span>
            }
            data-attr={dataAttr}
        />
    )
}
