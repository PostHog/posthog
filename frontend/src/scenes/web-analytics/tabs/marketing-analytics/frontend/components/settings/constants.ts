import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

export const defaultConversionGoalFilter: ConversionGoalFilter = {
    conversion_goal_id: '',
    conversion_goal_name: '',
    type: EntityTypes.EVENTS,
    id: null,
    name: null,
    schema: {
        utm_campaign_name: 'utm_campaign',
        utm_source_name: 'utm_source',
    },
}
