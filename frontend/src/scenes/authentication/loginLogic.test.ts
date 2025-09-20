import { router } from 'kea-router'
import { testUtilsPlugin } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { handleLoginRedirect, loginLogic } from 'scenes/authentication/loginLogic'

import { initKea } from '~/initKea'
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
})
