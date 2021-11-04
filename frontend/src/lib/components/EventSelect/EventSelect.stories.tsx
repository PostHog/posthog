import { Meta } from '@storybook/react'
import { Provider } from 'kea'
import { ResponseResolver, RestRequest, RestContext, rest } from 'msw'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { initKea } from '~/initKea'
import { worker } from '~/mocks/browser'
import { eventDefinitionsModel, EventDefinitionStorage } from '~/models/eventDefinitionsModel'
import { EventSelect } from './EventSelect'

export default {
    title: 'PostHog/Components/EventSelect',
    decorators: [
        (Story) => {
            worker.use(
                rest.get('/api/projects/:projectId', (_, res, ctx) => {
                    return res(ctx.json({ id: 2 }))
                })
            )

            return <Story />
        },
    ],
} as Meta

export const Default = (): JSX.Element => {
    const [selectedEvents, setSelectedEvents] = React.useState<string[]>([])

    worker.use(
        mockGetEventDefinitions((_, res, ctx) =>
            res(
                ctx.delay(1500),
                ctx.json({
                    count: 3,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '017cdbec-c38f-0000-1479-bc7b9e2b6c77',
                            name: '$autocapture',
                            volume_30_day: null,
                            query_usage_30_day: null,
                            description: '',
                        },
                        {
                            id: '017ce199-a10e-0000-6783-7167743302f4',
                            name: '$capture_failed_request',
                            volume_30_day: null,
                            query_usage_30_day: null,
                            description: '',
                        },
                        {
                            id: '017cdbee-0c77-0000-ecf1-bd5a9e253b92',
                            name: '$capture_metrics',
                            volume_30_day: null,
                            query_usage_30_day: null,
                            description: '',
                        },
                    ],
                })
            )
        )
    )

    initKea()
    eventDefinitionsModel.mount()

    // Need to mount teamLogic otherwise we get erros regarding not being able
    // to find the storre for team. It also makes some API calls to
    // `/api/projects/@current` and `/api/organizations/@current` although I
    // haven't mocked these as the component still works without doing so
    teamLogic.mount()

    return (
        <Provider>
            <EventSelect
                selectedEvents={selectedEvents}
                onChange={setSelectedEvents}
                addElement={<span>add events</span>}
            />
        </Provider>
    )
}

type GetEventDefinitionsResponse = EventDefinitionStorage
type GetEventDefinitionsRequest = undefined

// eslint-disable-next-line @typescript-eslint/explicit-module-boundary-types, @typescript-eslint/explicit-function-return-type
const mockGetEventDefinitions = (
    handler: ResponseResolver<RestRequest<GetEventDefinitionsRequest, any>, RestContext, GetEventDefinitionsResponse>
) =>
    rest.get<GetEventDefinitionsRequest, GetEventDefinitionsResponse>(
        '/api/projects/:projectId/event_definitions',
        handler
    )
