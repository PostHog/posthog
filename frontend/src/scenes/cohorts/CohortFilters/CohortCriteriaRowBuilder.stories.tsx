import { Meta } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import {
    CohortCriteriaRowBuilder,
    CohortCriteriaRowBuilderProps,
} from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { BehavioralEventType } from '~/types'

const meta: Meta<typeof CohortCriteriaRowBuilder> = {
    title: 'Filters/Cohort Filters/Row Builder',
    component: CohortCriteriaRowBuilder,
    decorators: [taxonomicFilterMocksDecorator],
}
export default meta

export function _CohortCriteriaRowBuilder(props: CohortCriteriaRowBuilderProps): JSX.Element {
    useMountedLogic(actionsModel)
    useMountedLogic(cohortsModel)
    useMountedLogic(cohortEditLogic({ id: 1 }))
    const [type, setType] = useState<BehavioralFilterType>(BehavioralEventType.PerformEvent)

    return (
        <Form logic={cohortEditLogic} props={{ id: 1 }} formKey="cohort">
            <CohortCriteriaRowBuilder {...props} criteria={{}} type={type} onChangeType={setType} />
        </Form>
    )
}
