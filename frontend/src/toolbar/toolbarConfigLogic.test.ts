import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
    } as any as Response)
)

describe('toolbar toolbarLogic', () => {
    let logic: ReturnType<typeof toolbarConfigLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = toolbarConfigLogic.build({ apiURL: 'http://localhost' })
        logic.mount()
    })

    it('is not authenticated', () => {
        expectLogic(logic).toMatchValues({ isAuthenticated: false })
    })

    it('normalizes uiHost to not end with a slash', () => {
        const logicWithUiHost = toolbarConfigLogic.build({
            posthog: { config: { ui_host: 'https://us.posthog.com/' } } as any,
        } as any)
        logicWithUiHost.mount()
        expect(logicWithUiHost.values.uiHost.endsWith('/')).toBe(false)
        expect(logicWithUiHost.values.uiHost).toBe('https://us.posthog.com')
    })
})
