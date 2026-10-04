import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SurveySchedule } from '~/types'

import { SurveyEventTrigger } from './SurveyEventTrigger'
import { SurveyEditSection, surveyLogic } from './surveyLogic'
import { WhenStep } from './wizard/steps/WhenStep'
import { surveyWizardLogic } from './wizard/surveyWizardLogic'

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

describe('Survey event trigger', () => {
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

    function mountSurveyWithTriggerEvent(
        schedule: SurveySchedule = SurveySchedule.Once,
        seenSurveyWaitPeriodInDays: number | null = null
    ): ReturnType<typeof surveyLogic.build> {
        const wizardLogic = surveyWizardLogic({ id: 'new' })
        wizardLogic.mount()
        const logic = surveyLogic({ id: 'new' })
        logic.mount()
        logic.actions.setSurveyValue('schedule', schedule)
        logic.actions.setSurveyValue('conditions', {
            events: {
                values: [{ name: 'signed_up' }],
                repeatedActivation: false,
            },
            seenSurveyWaitPeriodInDays,
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

    it('keeps the once per user hint when the schedule does not repeat the survey', () => {
        mountSurveyWithTriggerEvent(SurveySchedule.Once)

        render(
            <Provider>
                <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                    <SurveyEventTrigger />
                </BindLogic>
            </Provider>
        )

        expect(screen.getByText('Show every time these events fire (otherwise: once per user)')).toBeInTheDocument()
        expect(screen.queryByText('completion conditions section')).not.toBeInTheDocument()
    })

    it.each([
        ['without a wait period', null, 'so it shows again on each of these events. To show it once per person'],
        [
            'with a wait period',
            7,
            'so it shows again on each of these events, at most once every 7 days. To show it once per person',
        ],
    ])(
        'explains that an always schedule repeats the survey %s',
        async (_name, seenSurveyWaitPeriodInDays, expectedNote) => {
            const logic = mountSurveyWithTriggerEvent(SurveySchedule.Always, seenSurveyWaitPeriodInDays)

            render(
                <Provider>
                    <BindLogic logic={surveyLogic} props={{ id: 'new' }}>
                        <SurveyEventTrigger />
                    </BindLogic>
                </Provider>
            )

            expect(screen.getByText('Show every time these events fire')).toBeInTheDocument()
            const sectionLink = screen.getByText('completion conditions section')
            expect(sectionLink.closest('p')).toHaveTextContent(expectedNote)

            await userEvent.click(sectionLink)
            expect(logic.values.selectedSection).toEqual(SurveyEditSection.CompletionConditions)
        }
    )

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
