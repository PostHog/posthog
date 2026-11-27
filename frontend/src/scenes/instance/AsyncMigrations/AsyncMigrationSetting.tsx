import { LemonDivider } from '@posthog/lemon-ui'

import { RenderMetricValue } from 'scenes/instance/SystemStatus/RenderMetricValue'

import { InstanceSetting } from '~/types'

export function AsyncMigrationSetting({ setting }: { setting: InstanceSetting }): JSX.Element {
    return (
        <div>
            <h4>{setting.key}</h4>
            <p>{setting.description}</p>
            <div>
                {RenderMetricValue(null, {
                    key: setting.key,
                    value: setting.value,
                    value_type: setting.value_type,
                    emptyNullLabel: 'Unset',
                    isSecret: setting.is_secret,
                })}
            </div>
            <LemonDivider />
        </div>
    )
}
