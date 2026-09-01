import { FIELD_VALUES, renderField } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterType, CohortSelectorFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { BehavioralEventType, BehavioralLifecycleType, TimeUnitType } from '~/types'

describe('renderField time-unit options', () => {
    function timeUnitOptions(value: BehavioralFilterType): Record<string | number, unknown> {
        const element = renderField[FilterType.TimeUnit]({
            fieldKey: 'time_interval',
            criteria: { value },
        } as CohortSelectorFieldProps)
        const [groupType] = (element.props as CohortSelectorFieldProps).fieldOptionGroupTypes ?? []
        return groupType ? FIELD_VALUES[groupType].values : {}
    }

    it('omits hours from "performed event regularly" whose query window pins to -1d', () => {
        // An hour-scale window there inverts or collapses the range, so hours must not be selectable.
        expect(timeUnitOptions(BehavioralLifecycleType.PerformEventRegularly)).not.toHaveProperty(TimeUnitType.Hour)
    })

    it('keeps hours for criteria whose backend accepts an hour window', () => {
        expect(timeUnitOptions(BehavioralEventType.PerformSequenceEvents)).toHaveProperty(TimeUnitType.Hour)
    })
})
