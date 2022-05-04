import { handleLoginRedirect, loginLogic } from 'scenes/authentication/loginLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { initKea } from '~/initKea'
import { testUtilsPlugin } from 'kea-test-utils'

describe('loginLogic', () => {
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
            [`http://some-other.origin/bla`, '/bla'],
            ['//foo.bar', '//foo.bar'],
            ['/bla?haha', '/bla?haha'],
            ['/bla?haha#hoho', '/bla?haha#hoho'],
        ]

        for (const [next, result] of matches) {
            it(`for next param "${next}" it returns "${result}"`, () => {
                router.actions.push(next ? `${origin}/?next=${encodeURIComponent(next)}` : origin)
                handleLoginRedirect()
                const newPath =
                    router.values.location.pathname + router.values.location.search + router.values.location.hash
                expect(newPath).toEqual(result)
            })
        }
    })

    describe('redirect vulnerability', () => {
        beforeEach(() => {
            // Note, initKeaTests() is not called here because that uses a memory history, which doesn't throw on origin redirect
            initKea({ beforePlugins: [testUtilsPlugin] })
        })
        it('should throw an exception on redirecting to a different origin', () => {
            router.actions.push(`${origin}/login?next=//google.com`)
            expect(() => {
                handleLoginRedirect()
            }).toThrow()
        })
    })
})
