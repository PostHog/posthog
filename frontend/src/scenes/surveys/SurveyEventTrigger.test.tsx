import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyType } from '~/types'

import { SurveyEventTrigger } from './SurveyEventTrigger'
import { surveyLogic } from './surveyLogic'
import { WhenStep } from './wizard/steps/WhenStep'
import { surveyWizardLogic } from './wizard/surveyWizardLogic'

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: ({
        eventNames,
        excludedProperties,
        onChange,
    }: {
        eventNames: string[]
        excludedProperties?: Record<string, string[]>
        onChange: (filters: Record<string, any>[]) => void
    }) => (
        <div data-testid={`property-filters-${eventNames[0]}`}>
            <div>{`Property filters for ${eventNames[0]}`}</div>
            <div data-attr="excluded-properties">{(excludedProperties?.['event_properties'] ?? []).join(',')}</div>
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
        const wizardLogic = surveyWizardLogic({ id: 'new' })
        wizardLogic.mount()
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

        expect(await screen.findByText('No filters')).toBeInTheDocument()
        expect(screen.getByText('Property filters for signed_up')).toBeInTheDocument()
    })

    it('hides only array event properties from the filter picker', async () => {
        mountSurveyWithTriggerEvent()
        propertyDefinitionsModel.mount()
        propertyDefinitionsModel.actions.updatePropertyDefinitions({
            'event/plan': { id: 'plan', name: 'plan', property_type: PropertyType.String },
            'event/tags': { id: 'tags', name: 'tags', property_type: PropertyType.StringArray },
            // PostHog has not resolved a type for this one yet, which does not make it an array
            'event/checkout_step': { id: 'checkout_step', name: 'checkout_step', property_type: undefined },
        })

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <SurveyEventTrigger />
                </BindLogic>
            </Provider>
        )

        // Only the array property is excluded: an unresolved type filters fine and stays offered
        expect((await screen.findByTestId('excluded-properties')).textContent).toBe('tags')
    })

    it('shows inline property filters in the guided editor and persists changes', async () => {
        const logic = mountSurveyWithTriggerEvent()

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <BindLogic logic={surveyWizardLogic} props={{ id: 'new' }}>
                        <WhenStep />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )

        expect(
            screen.getByText('Each event can be narrowed with optional property filters right below it.')
        ).toBeInTheDocument()
        expect(screen.getByText('Property filters for signed_up')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Apply property filter'))

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
