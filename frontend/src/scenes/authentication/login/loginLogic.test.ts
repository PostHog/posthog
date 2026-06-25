import { router } from 'kea-router'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { handleLoginRedirect, loginLogic } from 'scenes/authentication/login/loginLogic'

import { initKea } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('loginLogic', () => {
    describe('redirect vulnerability', () => {
        beforeEach(() => {
            // Note, initKeaTests() is not called here because that uses a memory history, which doesn't throw on origin redirect
            initKea({ beforePlugins: [testUtilsPlugin] })
        })
        it('should ignore redirect attempt to a different origin', () => {
            router.actions.push(`${origin}/login?next=//google.com`)
            handleLoginRedirect()
            expect(router.values.location.pathname).toEqual('/')
        })
    })

    describe('parseLoginRedirectURL', () => {
        let logic: ReturnType<typeof loginLogic.build>

        beforeEach(() => {
            initKeaTests()
            logic = loginLogic()
            logic.mount()
        })

        const origin = `http://localhost`
        const matches = [
            [null, '/'],
            ['/', '/'],
            ['asdf', '/'],
            ['?next=javascript:something', '/'],
            ['javascript:something', '/'],
            ['/bla', '/bla'],
            [`${origin}/bla`, '/bla'],
            [`http://some-other.origin/bla`, '/'],
            ['//foo.bar', '/'],
            ['/bla?haha', '/bla?haha'],
            ['/bla?haha#hoho', '/bla?haha#hoho'],
        ]

        for (const [next, result] of matches) {
            it(`for next param "${next}" it returns "${result}"`, () => {
                if (next) {
                    const [nextPath, nextHash] = next.split('#')
                    // The hash is the only part of the URL that isn't sent to the server
                    router.actions.push(
                        `${origin}/?next=${encodeURIComponent(nextPath)}${nextHash ? `#` + nextHash : ''}`
                    )
                } else {
                    router.actions.push(origin)
                }
                handleLoginRedirect()
                const newPath =
                    router.values.location.pathname + router.values.location.search + router.values.location.hash
                expect(removeProjectIdIfPresent(newPath)).toEqual(result)
            })
        }
    })

    describe('precheck dedupe', () => {
        let logic: ReturnType<typeof loginLogic.build>
        let precheckHandler: jest.Mock

        beforeEach(() => {
            precheckHandler = jest.fn(() => [200, { saml_available: false }])
            useMocks({ post: { '/api/login/precheck': precheckHandler } })
            initKeaTests()
            router.actions.push('/login')
            logic = loginLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            jest.clearAllMocks()
        })

        it('skips a redundant precheck for an already-resolved email but re-runs for a new one', async () => {
            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            logic.actions.precheck({ email: 'a@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            expect(precheckHandler).toHaveBeenCalledTimes(1)

            logic.actions.precheck({ email: 'b@example.com' })
            await expectLogic(logic).toDispatchActions(['precheckSuccess'])
            expect(precheckHandler).toHaveBeenCalledTimes(2)
        })
    })
})
