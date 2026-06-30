import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { CohortCriteriaRowBuilder } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'

import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

describe('CohortCriteriaRowBuilder', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('renders empty and reports the unknown type instead of crashing when type has no ROWS entry', () => {
        // Guard: a type with no ROWS entry must render empty (not crash on rowShape.fields) and
        // surface the unknown type so it can't silently vanish from the editor.
        expect(() => {
            render(
                <Form logic={cohortEditLogic} props={{ id: 'new' }} formKey="cohort">
                    <CohortCriteriaRowBuilder
                        id="new"
                        criteria={{}}
                        type={'unrecognized_type_not_in_rows' as BehavioralFilterType}
                        groupIndex={0}
                        index={0}
                        logicalOperator={FilterLogicalOperator.And}
                    />
                </Form>
            )
        }).not.toThrow()
        expect(posthog.captureException).toHaveBeenCalled()
    })
})
