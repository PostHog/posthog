import { LemonBanner, LemonCard, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

export interface SelfDrivingSignalSourceToggleProps {
    /** Signal source product, named as it is in the inbox signal sources modal. */
    sourceName: string
    /** What this source emits, e.g. "evaluation report". */
    signalNoun: string
    /** `null` until the signal source configs resolve. */
    enabled: boolean | null
    loadFailed: boolean
    toggling: boolean
    onChange: () => void
    onRetry: () => void
    'data-attr': string
}

export function SelfDrivingSignalSourceToggle({
    sourceName,
    signalNoun,
    enabled,
    loadFailed,
    toggling,
    onChange,
    onRetry,
    'data-attr': dataAttr,
}: SelfDrivingSignalSourceToggleProps): JSX.Element {
    if (enabled === null) {
        if (loadFailed) {
            return (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry }}>
                    We couldn't load signal source settings. Try again in a moment.
                </LemonBanner>
            )
        }

        return <LemonSkeleton className="h-5 w-72 rounded" />
    }

    return (
        <LemonCard hoverEffect={false} className="flex items-center justify-between gap-3 p-3">
            <div className="flex flex-wrap items-baseline gap-1">
                <span className="font-medium">{sourceName} signal source</span>
                <span className="text-xs font-normal text-muted">Must be on to accept {signalNoun} signals.</span>
            </div>
            <LemonSwitch
                size="small"
                checked={enabled}
                onChange={onChange}
                loading={toggling}
                aria-label={`${sourceName} signal source`}
                data-attr={dataAttr}
            />
        </LemonCard>
    )
}
