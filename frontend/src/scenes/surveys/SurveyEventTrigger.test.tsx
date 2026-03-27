import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SurveyEventTrigger } from './SurveyEventTrigger'
import { surveyLogic } from './surveyLogic'
import { WhenStep } from './wizard/steps/WhenStep'

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: ({
        eventNames,
        onChange,
    }: {
        eventNames: string[]
        onChange: (filters: Record<string, any>[]) => void
    }) => (
        <div data-testid={`property-filters-${eventNames[0]}`}>
            <div>{`Property filters for ${eventNames[0]}`}</div>
            <button
                type="button"
                onClick={() => onChange([{ key: 'plan', value: ['pro'], operator: 'exact', type: 'event' }])}
            >
                Apply property filter
            </button>
        </div>
    ),
}))

describe('Survey event trigger property filters', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions': {
                    results: [
                        { name: 'plan', property_type: 'String' },
                        { name: 'payload', property_type: 'StringArray' },
                    ],
                    count: 2,
                },
                '/api/projects/:team_id/surveys': { results: [], count: 0 },
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    function mountSurveyWithTriggerEvent(): ReturnType<typeof surveyLogic.build> {
        const logic = surveyLogic({ id: 'new' })
        logic.mount()
        logic.actions.setSurveyValue('conditions', {
            events: {
                values: [{ name: 'signed_up' }],
                repeatedActivation: false,
            },
        })
        return logic
    }

    it('shows event property filters expanded by default in the full editor', async () => {
        mountSurveyWithTriggerEvent()

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <SurveyEventTrigger />
                </BindLogic>
            </Provider>
        )

        expect(await screen.findByText('Narrow this trigger to matching events only.')).toBeInTheDocument()
        expect(screen.getByText('No filters yet')).toBeInTheDocument()
        expect(screen.getByText('Property filters for signed_up')).toBeInTheDocument()
    })

    it('shows inline property filters in the guided editor and persists changes', async () => {
        const logic = mountSurveyWithTriggerEvent()

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <WhenStep />
                </BindLogic>
            </Provider>
        )

        expect(
            screen.getByText('Each event can be narrowed with optional property filters right below it.')
        ).toBeInTheDocument()
        expect(screen.getByText('Property filters for signed_up')).toBeInTheDocument()

        await userEvent.click(screen.getByRole('button', { name: 'Apply property filter' }))

        await waitFor(() => {
            if (!logic.values.survey.conditions?.events?.values?.[0].propertyFilters?.plan) {
                throw new Error('Property filters not updated yet')
            }
        })
        expect(logic.values.survey.conditions?.events?.values?.[0].propertyFilters).toEqual({
            plan: { values: ['pro'], operator: 'exact' },
        })
    })
})
