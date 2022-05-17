import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import {
    CohortCriteriaRowBuilder,
    CohortCriteriaRowBuilderProps,
} from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { cohortLogic } from 'scenes/cohorts/cohortLogic'
import { BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { BehavioralEventType } from '~/types'
import { Form } from 'kea-forms'

export default {
    title: 'Filters/Cohort Filters/Row Builder',
    component: CohortCriteriaRowBuilder,
    decorators: [taxonomicFilterMocksDecorator],
} as ComponentMeta<typeof CohortCriteriaRowBuilder>

export function _CohortCriteriaRowBuilder(props: CohortCriteriaRowBuilderProps): JSX.Element {
    useMountedLogic(actionsModel)
    useMountedLogic(cohortsModel)
    useMountedLogic(cohortLogic({ id: 1 }))
    const [type, setType] = useState<BehavioralFilterType>(BehavioralEventType.PerformEvent)
    return (
        <Form logic={cohortLogic} props={{ id: 1 }} formKey={'cohort'}>
            <CohortCriteriaRowBuilder {...props} criteria={{}} type={type} onChangeType={setType} />
        </Form>
    )
}
