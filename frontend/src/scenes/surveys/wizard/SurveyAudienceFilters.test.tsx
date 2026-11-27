import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { toPaginatedResponse } from '~/mocks/handlers'
import { useMocks } from '~/mocks/jest'
import { cohortsModel } from '~/models/cohortsModel'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'
import type { FeatureFlagFilters } from '~/types'

import { surveyLogic } from '../surveyLogic'
import { SurveyAudienceFilters } from './SurveyAudienceFilters'

const mockPropertyFilters = jest.fn()

const cohort = {
    id: 7,
    name: 'Opened billing twice',
    is_static: false,
    filters: { properties: { type: 'AND', values: [] } },
    realtime: { state: 'off', ready_at: null, build: null, reason: null, history_limit_days: null },
}

let mockRenderRealPropertyFilters = false

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => {
    const { PropertyFilters: RealPropertyFilters } = jest.requireActual(
        'lib/components/PropertyFilters/PropertyFilters'
    )
    return {
        PropertyFilters: (props: Record<string, unknown>) => {
            mockPropertyFilters(props)
            if (mockRenderRealPropertyFilters) {
                return <RealPropertyFilters {...props} />
            }
            return <div data-attr="audience-property-filters" data-testid="audience-property-filters" />
        },
    }
})

describe('SurveyAudienceFilters', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                '/api/projects/:team/surveys/responses_count': () => [200, {}],
                '/api/projects/:team/cohorts/': () => [200, toPaginatedResponse([cohort])],
                '/api/projects/:team/cohorts/:id/': () => [200, cohort],
            },
        })
        mockPropertyFilters.mockClear()
        mockRenderRealPropertyFilters = false
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

    it('tags and explains a cohort in the audience rules that has realtime off', async () => {
        mockRenderRealPropertyFilters = true
        cohortsModel.mount()
        await expectLogic(cohortsModel).toFinishAllListeners()

        const logic = surveyLogic({ id: 'new' })
        logic.mount()
        logic.actions.setSurveyValue('targeting_flag_filters', {
            groups: [
                {
                    properties: [
                        { type: PropertyFilterType.Cohort, key: 'id', value: cohort.id, operator: PropertyOperator.In },
                    ],
                    rollout_percentage: 100,
                    variant: null,
                },
            ],
            multivariate: null,
            payloads: {},
        })
        const { container } = render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <SurveyAudienceFilters />
                </BindLogic>
            </Provider>
        )

        await waitFor(() => {
            expect(container.querySelector('[data-attr="cohort-flag-targeting-notice"]')).toBeInTheDocument()
        })
        const pill = container.querySelector('.PropertyFilterButton')
        expect(pill).toBeInTheDocument()
        fireEvent.click(pill as Element)
        await waitFor(() => {
            expect(document.querySelector('[data-attr="cohort-realtime-tag"]')).toBeInTheDocument()
        })
    })
})
