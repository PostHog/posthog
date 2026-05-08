import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'
import type { FeatureFlagFilters } from '~/types'

import { surveyLogic } from '../surveyLogic'
import { SurveyAudienceFilters } from './SurveyAudienceFilters'

const mockPropertyFilters = jest.fn()

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: (props: Record<string, unknown>) => {
        mockPropertyFilters(props)
        return <div data-attr="audience-property-filters" data-testid="audience-property-filters" />
    },
}))

describe('SurveyAudienceFilters', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
            },
        })
        mockPropertyFilters.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('enables relative date options for guided audience rules', () => {
        const logic = surveyLogic({ id: 'new' })
        logic.mount()

        const targetingFilters: FeatureFlagFilters = {
            groups: [
                {
                    properties: [
                        {
                            key: 'last_signed_in_at',
                            value: '-7d',
                            operator: PropertyOperator.IsDateBefore,
                            type: PropertyFilterType.Person,
                        },
                    ],
                    rollout_percentage: 100,
                    variant: null,
                },
            ],
            multivariate: null,
            payloads: {},
        }

        logic.actions.setSurveyValue('targeting_flag_filters', targetingFilters)

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <SurveyAudienceFilters />
                </BindLogic>
            </Provider>
        )

        expect(screen.getByTestId('audience-property-filters')).toBeInTheDocument()
        expect(mockPropertyFilters).toHaveBeenCalledWith(
            expect.objectContaining({
                allowRelativeDateOptions: true,
                propertyFilters: targetingFilters.groups[0].properties,
            })
        )
    })
})
