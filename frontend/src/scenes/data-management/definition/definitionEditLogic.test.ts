import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinition } from '~/test/mocks'

describe('definitionEditLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
                '/api/projects/:team_id/event_definitions/': {
                    results: mockEventDefinitions,
                    count: mockEventDefinitions.length,
                },
                '/api/projects/:team_id/property_definitions/': {
                    results: [mockEventPropertyDefinition],
                    count: 1,
                },
            },
            patch: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
            },
        })
        initKeaTests()
        eventDefinitionsTableLogic.mount()
        propertyDefinitionsTableLogic.mount()
    })

    // The property branch reads `propertyAccessControlLogic`, which is only mounted when the
    // access-control panel renders (behind a feature flag). Saving with it unmounted must still
    // toast and navigate — guarded by `findMounted` in definitionEditLogic.
    it.each([
        {
            kind: 'event',
            id: '1',
            editUrl: urls.eventDefinitionEdit('1'),
            detailUrl: urls.eventDefinition(mockEventDefinitions[0].id),
            localAction: (): any =>
                eventDefinitionsTableLogic.actionCreators.setLocalEventDefinition(mockEventDefinitions[0]),
        },
        {
            kind: 'property',
            id: mockEventPropertyDefinition.id,
            editUrl: urls.propertyDefinitionEdit(mockEventPropertyDefinition.id),
            detailUrl: urls.propertyDefinition(mockEventPropertyDefinition.id),
            localAction: (): any =>
                propertyDefinitionsTableLogic.actionCreators.setLocalPropertyDefinition(mockEventPropertyDefinition),
        },
    ])('saves a $kind definition and navigates back', async ({ id, editUrl, detailUrl, localAction }) => {
        // isEvent is derived from the route, so set it before the definition loads
        router.actions.push(editUrl)
        await expectLogic(definitionLogic({ id })).toFinishAllListeners()

        const logic = definitionEditLogic({ id })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.saveDefinition({})
        }).toDispatchActionsInAnyOrder(['saveDefinition', 'setDefinition', localAction()])

        // navigated away from the edit page back to the definition detail page
        expect(router.values.location.pathname.endsWith(detailUrl)).toBe(true)
    })

    // The form holds the owner as a user object, but the API takes a user id
    it.each([
        {
            change: 'assigns',
            savedOwner: null,
            editedOwner: MOCK_DEFAULT_BASIC_USER,
            sentOwner: MOCK_DEFAULT_BASIC_USER.id,
        },
        {
            change: 'keeps',
            savedOwner: MOCK_DEFAULT_BASIC_USER,
            editedOwner: undefined,
            sentOwner: MOCK_DEFAULT_BASIC_USER.id,
        },
        { change: 'clears', savedOwner: MOCK_DEFAULT_BASIC_USER, editedOwner: null, sentOwner: null },
    ])('$change the event owner on save', async ({ savedOwner, editedOwner, sentOwner }) => {
        let requestBody: Record<string, unknown> | undefined
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/:id': { ...mockEventDefinitions[0], owner: savedOwner },
            },
            patch: {
                '/api/projects/:team/event_definitions/:id': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [
                        200,
                        { ...mockEventDefinitions[0], owner: requestBody.owner ? MOCK_DEFAULT_BASIC_USER : null },
                    ]
                },
            },
        })
        router.actions.push(urls.eventDefinitionEdit('1'))
        const logic = definitionEditLogic({ id: '1' })
        logic.mount()
        await expectLogic(definitionLogic({ id: '1' })).toDispatchActions(['loadDefinitionSuccess'])
        expect(logic.values.editDefinition).toMatchObject({ owner: savedOwner })
        if (editedOwner !== undefined) {
            logic.actions.setEditDefinitionValue('owner', editedOwner)
        }

        await expectLogic(logic, () => {
            logic.actions.saveDefinition({})
        }).toDispatchActions(['saveDefinitionSuccess'])

        expect(requestBody?.owner).toBe(sentOwner)
    })
})
