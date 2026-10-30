import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { Form } from 'kea-forms'

import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockGetEventDefinitionsFrom } from '~/test/mocks'
import { CyclotronJobFiltersType, HogFunctionConfigurationType, HogFunctionTemplateType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { HogFunctionMappings } from '../mapping/HogFunctionMappings'
import { HogFunctionFilters } from './HogFunctionFilters'

// react-virtualized renders no rows without real DOM measurements.
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const LOGIC_PROPS = { templateId: 'template-webhook' }

const PAGEVIEW_FILTERS: CyclotronJobFiltersType = {
    events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
}

const TEMPLATE: HogFunctionTemplateType = {
    free: true,
    status: 'stable',
    id: 'template-webhook',
    type: 'destination',
    name: 'HTTP Webhook',
    description: 'Sends a webhook',
    code: 'print(event)',
    code_language: 'hog',
    inputs_schema: [],
    filters: PAGEVIEW_FILTERS,
    icon_url: '/static/posthog-icon.svg',
}

describe('destination event matchers', () => {
    beforeEach(() => {
        // Recent picks persist in localStorage. Without this, a pick in one case shows up in the next.
        localStorage.clear()
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            flag_evaluations_mode: FlagEvaluationsModeEnumApi.Number2,
        })
    })

    afterEach(cleanup)

    it.each([
        {
            matcher: 'the destination filters',
            template: TEMPLATE,
            matchedEvents: (configuration: HogFunctionConfigurationType) => configuration.filters?.events,
        },
        {
            matcher: 'a mapping',
            template: {
                ...TEMPLATE,
                filters: null,
                mapping_templates: [{ name: 'Track', include_by_default: true, filters: PAGEVIEW_FILTERS }],
            },
            matchedEvents: (configuration: HogFunctionConfigurationType) =>
                configuration.mappings?.[0]?.filters?.events,
        },
    ])(
        'lets a team on flag evaluations mode 2 match Feature flag called in $matcher',
        async ({ template, matchedEvents }) => {
            useMocks({
                get: {
                    '/api/projects/:team/hog_function_templates/:id': template,
                    '/api/projects/:team/event_definitions': mockGetEventDefinitionsFrom([
                        { ...mockEventDefinitions[0], id: 'flag-called', name: '$feature_flag_called' },
                    ]),
                },
            })
            const logic = hogFunctionConfigurationLogic(LOGIC_PROPS)
            logic.mount()
            // HogFunctionConfiguration renders both. Each template leaves exactly one of them with an event matcher.
            render(
                <BindLogic logic={hogFunctionConfigurationLogic} props={LOGIC_PROPS}>
                    <Form logic={hogFunctionConfigurationLogic} props={LOGIC_PROPS} formKey="configuration">
                        <HogFunctionFilters />
                        <HogFunctionMappings />
                    </Form>
                </BindLogic>
            )

            fireEvent.click(await screen.findByTestId('trend-element-subject-0'))
            fireEvent.click(await screen.findByText('Feature flag called'))

            await waitFor(() => {
                expect(matchedEvents(logic.values.configuration)?.map((event) => event.id)).toEqual([
                    '$feature_flag_called',
                ])
            })
        }
    )
})
