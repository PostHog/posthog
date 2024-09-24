import { LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { HogFunctionFiltersActivityLog } from './HogFunctionFiltersActivityLog'
import { HogFunctionFiltersAlerts } from './HogFunctionFiltersAlerts'
import { HogFunctionFiltersEvents } from './HogFunctionFiltersEvents'

export function HogFunctionFilters(): JSX.Element {
    const { configuration } = useValues(hogFunctionConfigurationLogic)

    return (
        <div className="border bg-bg-light rounded p-3 space-y-2">
            <LemonField name="trigger" label="Trigger source">
                <LemonSelect
                    options={[
                        {
                            value: 'event',
                            label: 'Events',
                            labelInMenu: (
                                <div>
                                    Events
                                    <br />
                                    <span className="text-xs text-muted-alt">Incoming real-time PostHog events</span>
                                </div>
                            ),
                        },
                        {
                            value: 'activity_log',
                            label: 'Team activity',
                            labelInMenu: (
                                <div>
                                    Team activity
                                    <br />
                                    <span className="text-xs text-muted-alt">
                                        Changes in PostHog such as an Insight being created
                                    </span>
                                </div>
                            ),
                        },
                        {
                            value: 'alert',
                            label: 'Alerts',
                            labelInMenu: (
                                <div>
                                    Alerts
                                    <br />
                                    <span className="text-xs text-muted-alt">
                                        React to alerts created in PostHog such as for an Insight threshold being
                                        reached
                                    </span>
                                </div>
                            ),
                        },
                    ]}
                />
            </LemonField>

            {configuration.trigger === 'event' ? (
                <HogFunctionFiltersEvents />
            ) : configuration.trigger === 'alert' ? (
                <HogFunctionFiltersAlerts />
            ) : configuration.trigger === 'activity_log' ? (
                <HogFunctionFiltersActivityLog />
            ) : (
                <span>Something went wrong...</span>
            )}
        </div>
    )
}
