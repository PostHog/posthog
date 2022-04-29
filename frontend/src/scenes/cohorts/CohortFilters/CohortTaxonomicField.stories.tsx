import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { CohortTaxonomicField } from './CohortField'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTaxonomicFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

export default {
    title: 'Filters/Cohort Filters/Fields/Taxonomic',
    component: CohortTaxonomicField,
    decorators: [taxonomicFilterMocksDecorator],
} as ComponentMeta<typeof CohortTaxonomicField>

const Template: ComponentStory<typeof CohortTaxonomicField> = (props: CohortTaxonomicFieldProps) => {
    useMountedLogic(actionsModel)
    const [value, setValue] = useState<string | null>(null)
    return renderField[FilterType.EventsAndActions]({
        ...props,
        value,
        onChange: (key) => setValue(String(key)),
    })
}

export const EventsAndActions = Template.bind({})
EventsAndActions.args = {
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    placeholder: 'Choose event or action',
}

export const EventProperties = Template.bind({})
EventProperties.args = {
    taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
    placeholder: 'Choose event property',
}
