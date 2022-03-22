import { handleLoginRedirect } from 'scenes/authentication/loginLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'

describe('loginLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('parseLoginRedirectURL', () => {
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
})
