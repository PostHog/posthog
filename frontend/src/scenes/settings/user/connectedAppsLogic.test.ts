import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ConnectedApp, connectedAppsLogic } from './connectedAppsLogic'

const APP_A: ConnectedApp = {
    id: 'app-a',
    name: 'App A',
    logo_uri: null,
    scopes: ['read'],
    authorized_at: '2026-06-18T00:00:00Z',
    is_verified: true,
    is_first_party: false,
}

const APP_B: ConnectedApp = {
    id: 'app-b',
    name: 'App B',
    logo_uri: null,
    scopes: ['read'],
    authorized_at: '2026-06-10T00:00:00Z',
    is_verified: false,
    is_first_party: false,
}

async function waitForInFlightRevoke(getResolve: () => (() => void) | undefined): Promise<() => void> {
    for (let attempt = 0; attempt < 100; attempt++) {
        const resolve = getResolve()
        if (resolve) {
            return resolve
        }
        await new Promise((r) => setTimeout(r, 0))
    }
    throw new Error('revoke request was never in flight')
}

describe('connectedAppsLogic', () => {
    let logic: ReturnType<typeof connectedAppsLogic.build>
    let resolveRevoke: (() => void) | undefined

    beforeEach(() => {
        resolveRevoke = undefined
        useMocks({
            get: {
                '/api/oauth/connected-apps/': () => [200, [APP_A, APP_B]],
            },
            post: {
                '/api/oauth/connected-apps/:id/revoke/': async () => {
                    await new Promise<void>((resolve) => {
                        resolveRevoke = resolve
                    })
                    return [200, null]
                },
            },
        })
        initKeaTests()
        logic = connectedAppsLogic()
        logic.mount()
    })

    it('removes an app from the list when revoked', async () => {
        jest.spyOn(lemonToast, 'success')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.revokeApp(APP_A.id)
        ;(await waitForInFlightRevoke(() => resolveRevoke))()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                connectedApps: [APP_B],
            })
        expect(lemonToast.success).toHaveBeenCalled()
    })

    it('does not toast when the logic unmounts mid-revoke', async () => {
        jest.spyOn(lemonToast, 'success')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.revokeApp(APP_A.id)
        const resolve = await waitForInFlightRevoke(() => resolveRevoke)
        logic.unmount()
        resolve()
        await new Promise((r) => setTimeout(r, 0))

        expect(lemonToast.success).not.toHaveBeenCalled()
    })
})
