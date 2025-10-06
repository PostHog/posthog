import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTaxonomicFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { actionsModel } from '~/models/actionsModel'

import { CohortTaxonomicField } from './CohortField'

type Story = StoryObj<typeof CohortTaxonomicField>
const meta: Meta<typeof CohortTaxonomicField> = {
    title: 'Filters/Cohort Filters/Fields/Taxonomic',
    component: CohortTaxonomicField,
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

const Template: StoryFn<typeof CohortTaxonomicField> = (props: CohortTaxonomicFieldProps) => {
    useMountedLogic(actionsModel)
    const [value, setValue] = useState<string | undefined>('')
    const type =
        props.taxonomicGroupTypes &&
        props.taxonomicGroupTypes.length === 2 &&
        props.taxonomicGroupTypes[0] === TaxonomicFilterGroupType.Events &&
        props.taxonomicGroupTypes[1] === TaxonomicFilterGroupType.Actions
            ? FilterType.EventsAndActions
            : FilterType.PersonProperties
    return renderField[type]({
        ...props,
        criteria: {
            key: value,
        },
        onChange: (key) => setValue(String(key)),
    })
}

export const EventsAndActions: Story = Template.bind({})
EventsAndActions.args = {
    taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    placeholder: 'Choose event or action',
}

export const PersonProperties: Story = Template.bind({})
PersonProperties.args = {
    taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties],
    placeholder: 'Choose person property',
}
