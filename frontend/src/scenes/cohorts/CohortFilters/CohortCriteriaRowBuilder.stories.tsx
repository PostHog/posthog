import React, { useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import {
    CohortCriteriaRowBuilderProps,
    CohortCriteriaRowBuilder,
} from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { BehavioralEventType } from '~/types'
import { BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { taxonomicFilterMocksDecorator } from 'lib/components/TaxonomicFilter/__mocks__/taxonomicFilterMocksDecorator'
import { useMountedLogic } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'

export default {
    title: 'Filters/Cohort Filters/Row Builder',
    component: CohortCriteriaRowBuilder,
    decorators: [taxonomicFilterMocksDecorator],
} as ComponentMeta<typeof CohortCriteriaRowBuilder>

export function _CohortCriteriaRowBuilder(props: CohortCriteriaRowBuilderProps): JSX.Element {
    useMountedLogic(actionsModel)
    useMountedLogic(cohortsModel)
    const [type, setType] = useState<BehavioralFilterType>(BehavioralEventType.PerformEvent)
    return <CohortCriteriaRowBuilder {...props} type={type} onChangeType={setType} />
}
