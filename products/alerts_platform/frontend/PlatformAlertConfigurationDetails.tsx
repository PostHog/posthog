import { TZLabel } from 'lib/components/TZLabel'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import {
    SOURCE_KINDS,
    configurationStatus,
    describeCondition,
    describeQuietHours,
    describeSchedule,
} from './platformAlertFormat'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'

export function PlatformAlertConfigurationDetails({
    configuration,
}: {
    configuration: PlatformAlertConfigurationApi
}): JSX.Element {
    const rows: [string, JSX.Element | string | number][] = [
        ['Source', SOURCE_KINDS[configuration.source_kind].label],
        ['Status', <PlatformAlertStatusTag key="status" status={configurationStatus(configuration)} />],
        ['Condition', describeCondition(configuration)],
        ['Schedule', describeSchedule(configuration)],
        ['Fires after', `${configuration.datapoints_to_alarm} of ${configuration.evaluation_periods} checks breach`],
        ['Cooldown', `${configuration.cooldown_minutes} min`],
        ['Quiet hours', describeQuietHours(configuration)],
        ['Next check', <OptionalTimeLabel key="next" time={configuration.next_check_at} fallback="Not scheduled" />],
        ['Failed checks in a row', configuration.consecutive_failures],
        ['Configuration ID', configuration.id],
        ['Legacy configuration ID', configuration.legacy_configuration_id ?? 'None'],
        ['Created', <TZLabel key="created" time={configuration.created_at} />],
        ['Updated', <TZLabel key="updated" time={configuration.updated_at} />],
    ]
    return (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 m-0">
            {rows.map(([label, value]) => (
                <div key={label} className="contents">
                    <dt className="text-secondary">{label}</dt>
                    <dd className="m-0 break-all">{value}</dd>
                </div>
            ))}
        </dl>
    )
}
