import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

export const defaultConversionGoalFilter: ConversionGoalFilter = {
    conversion_goal_id: '',
    conversion_goal_name: '',
    kind: NodeKind.EventsNode,
    event: '',
    name: 'Select event, custom event or any data warehouse table',
    math: BaseMathType.TotalCount,
    schema: {
        utm_campaign_name: 'utm_campaign',
        utm_source_name: 'utm_source',
    },
}
