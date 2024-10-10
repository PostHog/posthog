import { LemonInputSelect, LemonLabel } from '@posthog/lemon-ui'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { ACTIVITY_LOG_ITEM_ACTIVITIES, ActivityScope } from '~/types'

export function HogFunctionFiltersActivityLog(): JSX.Element {
    return (
        <>
            <LemonField name="filters">
                {({ value, onChange }) => (
                    <>
                        <LemonLabel>Scopes</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={Object.values(ActivityScope)
                                .sort()
                                .map((x) => ({
                                    key: x,
                                    label: humanizeScope(x),
                                }))}
                            placeholder="Choose which activities to trigger on (leave empty to trigger on all)"
                            value={value?.scope ?? []}
                            onChange={(scope) => onChange({ ...value, scope })}
                        />

                        <LemonLabel>Activity types</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={ACTIVITY_LOG_ITEM_ACTIVITIES.map((x) => ({
                                key: x,
                                label: x,
                            }))}
                            placeholder="(Optional) The kind of activity to trigger on"
                            value={value?.activity ?? []}
                            onChange={(activity) => onChange({ ...value, activity })}
                            allowCustomValues
                        />

                        <LemonLabel>Item IDs</LemonLabel>
                        <LemonInputSelect
                            mode="multiple"
                            options={[]}
                            placeholder="(Optional) Choose specific item IDs to trigger on"
                            value={value?.item_id ?? []}
                            onChange={(item_id) => onChange({ ...value, item_id })}
                            allowCustomValues
                        />
                    </>
                )}
            </LemonField>
        </>
    )
}
