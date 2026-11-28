import { MOCK_TEAM_ID } from 'lib/api.mock'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActionType } from '~/types'

import { deleteActionWithWarning } from './deleteAction'

describe('deleteActionWithWarning', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    // A delete only changes `deleted`. Sending the action back re-runs name validation, which rejects
    // a blank name with "This field may not be blank", so an unnamed action could never be deleted.
    it('sends only deleted for an action with a blank name, and the undo does the same', async () => {
        const action = { id: 7, name: '', steps: [] } as unknown as ActionType
        const patchedBodies: Record<string, any>[] = []
        useMocks({
            get: {
                '/api/projects/:team/actions/:id/references/': [],
            },
            patch: {
                '/api/projects/:team/actions/:id/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    patchedBodies.push(body)
                    return [200, { ...action, ...body }]
                },
            },
        })
        initKeaTests()
        const infoSpy = jest.spyOn(lemonToast, 'info')
        const callback = jest.fn()

        await deleteActionWithWarning(MOCK_TEAM_ID, action, callback)

        expect(patchedBodies).toEqual([{ deleted: true }])
        expect(callback).toHaveBeenLastCalledWith(false, action)

        await infoSpy.mock.calls[0][1]?.button?.action()

        expect(patchedBodies).toEqual([{ deleted: true }, { deleted: false }])
        expect(callback).toHaveBeenLastCalledWith(true, action)
    })
})
