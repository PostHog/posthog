import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { renderField } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTaxonomicFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'

import { actionsModel } from '~/models/actionsModel'

import { CohortTaxonomicField } from './CohortField'

type Story = StoryObj<CohortTaxonomicFieldProps>
const meta: Meta<CohortTaxonomicFieldProps> = {
    title: 'Filters/Cohort Filters/Fields/Taxonomic',
    component: CohortTaxonomicField,
    decorators: [taxonomicFilterMocksDecorator],
    render: (props) => {
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
    },
}
export default meta

export const EventsAndActions: Story = {
    args: {
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
        placeholder: 'Choose event or action',
    },
}

export const PersonProperties: Story = {
    args: {
        taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties],
        placeholder: 'Choose person property',
    },
}
