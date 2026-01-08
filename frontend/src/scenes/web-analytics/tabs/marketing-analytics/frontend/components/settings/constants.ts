import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

export const defaultConversionGoalFilter: ConversionGoalFilter = {
    conversion_goal_id: '',
    conversion_goal_name: '',
    kind: NodeKind.EventsNode,
    event: '',
    name: 'Select event, custom event, action or any data warehouse table',
    math: BaseMathType.TotalCount,
    schema_map: {
        utm_campaign_name: 'utm_campaign',
        utm_source_name: 'utm_source',
        timestamp_field: 'timestamp',
        distinct_id_field: 'distinct_id',
    },
}

export const conversionGoalDescription =
    'Select which core events to use as conversion goals for marketing attribution.'

export const conversionGoalNamePlaceholder = 'Conversion goal name, e.g. purchase, sign up, download'

export const getConfiguredConversionGoalsLabel = (count: number): string => `Enabled core events (${count})`
