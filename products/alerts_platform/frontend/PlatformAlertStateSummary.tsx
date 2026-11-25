import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { configurationStateCounts } from './platformAlertFormat'
import { PlatformAlertStateLabel } from './PlatformAlertStateLabel'

export function PlatformAlertStateSummary({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element {
    const showCounts = configuration.enabled && configuration.alerts.length > 1
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {configurationStateCounts(configuration).map(({ status, count }) => (
                <PlatformAlertStateLabel key={status} status={status} count={showCounts ? count : undefined} />
            ))}
        </div>
    )
}
