import { LemonSelect } from '@posthog/lemon-ui'

export function RetentionMeasure(): JSX.Element {
    return (
        <div className="space-y-2" data-attr="retention-summary">
            {/* <div className="flex items-center">
                <LemonSegmentedButton
                    options={[
                        {
                            value: 'Retention rate',
                            label: 'Retention rate',
                            // tooltip: 'Percent',
                        },
                        {
                            value: 'Property value',
                            label: 'Property value',
                            // tooltip: 'Absolute number',
                        },
                    ]}
                    value="Retention rate"
                />
            </div> */}
            <div className="flex items-center gap-2">
                <div>When users return</div>
                <LemonSelect
                    options={[
                        {
                            label: 'on each interval',
                            value: 'on each interval',
                            tooltip: 'Users are counted once per interval',
                        },
                        {
                            label: 'on or after each interval',
                            value: 'on or after each interval',
                            tooltip:
                                'Also know as rolling, or unbounded retention. Includes any subsequent time period, instead of only the next period. For example, if a user is comes back on day 7, they are counted in all previous retention periods.',
                        },
                        // {
                        //     label: 'every interval',
                        //     value: 'every interval',
                        // },
                    ]}
                    value="on each interval"
                    // onChange={(value): void => updateInsightFilter({ retentionType: value as RetentionType })}
                    // dropdownMatchSelectWidth={false}
                />
            </div>
            {/* for <all groups/1 day/7th day>... */}
        </div>
    )
}
