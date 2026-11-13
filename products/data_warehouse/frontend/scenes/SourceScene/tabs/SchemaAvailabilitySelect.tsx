import { LemonSelect } from '@posthog/lemon-ui'

import { ExternalDataSourceSchema } from '~/types'

import { SchemaAvailability, schemaAvailability } from './sourceSettingsLogic'

interface SchemaAvailabilitySelectProps {
    schema: ExternalDataSourceSchema
    onChange: (availability: SchemaAvailability) => void
    saving: boolean
    /** Set by the access control wrapper when the user can't edit this table. */
    disabledReason?: string | null
}

function OptionLabel({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div className="flex flex-col py-0.5">
            <span>{title}</span>
            <span className="text-xs text-muted">{description}</span>
        </div>
    )
}

export function SchemaAvailabilitySelect({
    schema,
    onChange,
    saving,
    disabledReason,
}: SchemaAvailabilitySelectProps): JSX.Element {
    return (
        <LemonSelect<SchemaAvailability>
            size="xsmall"
            value={schemaAvailability(schema)}
            onChange={onChange}
            loading={saving}
            disabledReason={disabledReason}
            dropdownMatchSelectWidth={false}
            data-attr="schemas-tab-availability-select"
            options={[
                {
                    value: 'synced',
                    label: 'Synced',
                    labelInMenu: <OptionLabel title="Synced" description="Copied to PostHog, and queryable live" />,
                },
                {
                    value: 'live',
                    label: 'Live only',
                    labelInMenu: <OptionLabel title="Live only" description="Queried from your database, not copied" />,
                    disabledReason: schema.live_query_unavailable_reason ?? undefined,
                },
                {
                    value: 'off',
                    label: 'Off',
                    labelInMenu: <OptionLabel title="Off" description="Not synced or queryable" />,
                },
            ]}
        />
    )
}
