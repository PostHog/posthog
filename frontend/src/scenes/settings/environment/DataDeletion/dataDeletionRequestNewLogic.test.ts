import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataDeletionRequestNewLogic } from './dataDeletionRequestNewLogic'

const PREVIEWED_QUERY = "SELECT uuid FROM events WHERE event = 'previewed_event'"
const EDITED_QUERY = "SELECT uuid FROM events WHERE event = 'edited_event'"

describe('dataDeletionRequestNewLogic', () => {
    let logic: ReturnType<typeof dataDeletionRequestNewLogic.build>
    let createdBodies: Record<string, unknown>[]

    beforeEach(() => {
        createdBodies = []
        useMocks({
            post: {
                '/api/projects/:project_id/data_deletion_requests/preview/': () => [200, { count: 3 }],
                '/api/projects/:project_id/data_deletion_requests/': async ({ request }) => {
                    const body = await request.json()
                    createdBodies.push(body)
                    return [201, { id: 'request-id', status: 'pending', query: body.query }]
                },
            },
        })
        initKeaTests()
        logic = dataDeletionRequestNewLogic()
        logic.mount()
    })

    async function previewAndConfirm(query: string): Promise<void> {
        logic.actions.setQueryInput(query)
        await expectLogic(logic, () => logic.actions.previewQuery()).toFinishAllListeners()
        logic.actions.setConfirmationText('delete events')
    }

    it('submits the previewed query with a submission id', async () => {
        await previewAndConfirm(PREVIEWED_QUERY)
        await expectLogic(logic).toMatchValues({ submitDisabledReason: null })

        await expectLogic(logic, () => logic.actions.submitRequest()).toFinishAllListeners()

        expect(createdBodies).toEqual([{ query: PREVIEWED_QUERY, submission_id: expect.any(String) }])
    })

    it('blocks submission again when the query changes after the preview', async () => {
        await previewAndConfirm(PREVIEWED_QUERY)

        logic.actions.setQueryInput(EDITED_QUERY)

        await expectLogic(logic).toMatchValues({
            currentPreview: null,
            confirmationText: '',
            submitDisabledReason: 'Check matching events first',
        })
    })
})
