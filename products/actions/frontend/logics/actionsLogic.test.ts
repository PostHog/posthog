import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { initKeaTests } from '~/test/init'
import { ActionType, AppContext, UserBasicType } from '~/types'

import { actionsLogic } from './actionsLogic'

let actionId = 1
const makeAction = (name: string, overrides: Partial<ActionType> = {}): ActionType => {
    actionId += 1
    return {
        id: actionId,
        name,
        description: '',
        tags: [],
        steps: [],
        created_by: { uuid: 'USER_UUID' } as UserBasicType,
        ...overrides,
    } as ActionType
}

describe('actionsLogic', () => {
    let logic: ReturnType<typeof actionsLogic.build>

    // Seed containing one action that matches "mcp" exactly and several whose names have
    // m/c/p characters spread across them — close enough to fuzzy-match when Fuse's
    // effective edit budget grows. With threshold 0.3, a 3-char query allows 0 errors,
    // but a trailing space makes the pattern 4 chars long and allows 1 error, which is
    // enough to let names like "Map clicked" or "SMTP delivered" leak in.
    const actionsSeed: ActionType[] = [
        makeAction('MCP server'),
        makeAction('Signed up'),
        makeAction('Page viewed'),
        makeAction('Checkout completed'),
        makeAction('Camp fire started'),
        makeAction('Map clicked'),
        makeAction('Payment tapped'),
        makeAction('SMTP delivered'),
        makeAction('NPM published'),
        makeAction('Stripe captured'),
        makeAction('Upload complete'),
        makeAction('Compose message'),
        makeAction('Mask applied'),
        makeAction('Compute provisioned'),
        makeAction('CMP accepted'),
        makeAction('Shop checkout'),
        makeAction('Signup complete'),
        makeAction('Login succeeded'),
        makeAction('Logout clicked'),
        makeAction('Comment posted'),
    ]

    beforeEach(async () => {
        window.POSTHOG_APP_CONTEXT = { current_user: MOCK_DEFAULT_USER } as unknown as AppContext

        useMocks({
            get: {
                '/api/projects/:team/actions/': {
                    count: actionsSeed.length,
                    next: null,
                    previous: null,
                    results: actionsSeed,
                },
            },
        })

        initKeaTests()

        actionsModel({ params: 'include_count=1' }).mount()
        await expectLogic(actionsModel).toDispatchActions(['loadActionsSuccess'])

        logic = actionsLogic()
        logic.mount()
    })

    it('shows all actions when no search term', () => {
        expect(logic.values.actionsFiltered).toHaveLength(actionsSeed.length)
    })

    it.each([['mcp'], ['mcp '], [' mcp'], [' mcp '], ['mcp\t']])(
        'returns only MCP server when searching for "%s"',
        async (term) => {
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm(term)
            }).toMatchValues({
                actionsFiltered: [expect.objectContaining({ name: 'MCP server' })],
            })
        }
    )
})
