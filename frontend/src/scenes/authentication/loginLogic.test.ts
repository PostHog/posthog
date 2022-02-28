import { afterLoginRedirect } from 'scenes/authentication/loginLogic'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'

describe('loginLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('afterLoginRedirect', () => {
        const origin = `http://localhost`
        const matches = [
            [null, '/'],
            ['/', '/'],
            ['/bla', '/bla'],
            ['asdf', '/'],
            ['http://hahaha/bla', '/bla'],
            ['javascript:something', '/'],
            ['?next=javascript:something', '/'],
            ['/bla?haha', '/bla?haha'],
            ['/bla?haha#hoho', '/bla?haha#hoho'],
        ]

        for (const [next, result] of matches) {
            it(`for next param "${next}" it returns "${result}"`, () => {
                router.actions.push(next ? `${origin}/?next=${encodeURIComponent(next)}` : origin)
                expect(afterLoginRedirect()).toEqual(result)
            })
        }
    })
})
