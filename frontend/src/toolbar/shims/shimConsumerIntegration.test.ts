jest.mock('scenes/userLogic', () => require('~/toolbar/shims/userLogic'))
jest.mock('scenes/organization/membersLogic', () => require('~/toolbar/shims/membersLogic'))
jest.mock('scenes/sceneLogic', () => require('~/toolbar/shims/sceneLogic'))
jest.mock('scenes/teamLogic', () => require('~/toolbar/shims/teamLogic'))
jest.mock('lib/logic/featureFlagLogic', () => require('~/toolbar/shims/featureFlagLogic'))
jest.mock('lib/api', () => ({
    __esModule: true,
    default: { get: jest.fn().mockResolvedValue(null), update: jest.fn().mockResolvedValue(null) },
}))

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

global.fetch = jest.fn(() =>
    Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
    } as any as Response)
)

describe('shim consumer integration', () => {
    beforeEach(() => {
        initKeaTests(false)
        toolbarConfigLogic.build({ apiURL: 'http://localhost' }).mount()
        jest.clearAllMocks()
    })

    describe('hedgehogModeLogic with shims', () => {
        it('mounts without error and has shimmed defaults', async () => {
            const { hedgehogModeLogic } = await import('~/lib/components/HedgehogMode/hedgehogModeLogic')
            const logic = hedgehogModeLogic.build()

            expect(() => logic.mount()).not.toThrow()
            expect(logic.values.hedgehogMode).toBeNull()
            expect(logic.values.user).toBeNull()
        })

        it('afterMount falls through to loadRemoteConfig when shimmed user is null', async () => {
            const { hedgehogModeLogic } = await import('~/lib/components/HedgehogMode/hedgehogModeLogic')
            const logic = hedgehogModeLogic.build()

            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadRemoteConfig'])
        })
    })

    describe('themeLogic with shims', () => {
        it('mounts without error and provides isDarkModeOn', async () => {
            const { themeLogic } = await import('~/layout/navigation-3000/themeLogic')
            const logic = themeLogic.build()
            logic.mount()

            expect(typeof logic.values.isDarkModeOn).toBe('boolean')
        })

        it('isDarkModeOn falls through to system preference when sceneConfig is null', async () => {
            const { themeLogic } = await import('~/layout/navigation-3000/themeLogic')
            const logic = themeLogic.build()
            logic.mount()

            const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
            expect(logic.values.isDarkModeOn).toBe(systemPrefersDark)
        })
    })

    describe('teamLogic shim contract', () => {
        it('provides weekStartDay for DateFilter', () => {
            const { teamLogic } = require('scenes/teamLogic')
            teamLogic.mount()
            expect(teamLogic.values.weekStartDay).toBe(0)
            expect(teamLogic.values.timezone).toBe('UTC')
        })
    })
})
