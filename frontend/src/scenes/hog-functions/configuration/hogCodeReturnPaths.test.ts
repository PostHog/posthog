import { canFinishWithoutReturn } from './hogCodeReturnPaths'

describe('canFinishWithoutReturn', () => {
    test.each([
        ['no return at all', `event.properties.tagged := true`],
        [
            'an if/else that returns in one branch only',
            `if (event.event == 'a') { event.properties.x := 1 } else { return event }`,
        ],
        ['an if without an else', `if (event.event == 'a') { return event }`],
        ['an else-if chain without a final else', `if (a) { return event } else if (b) { return event }`],
        ['a catch that does not return', `try { return event } catch (e) { print(e) }`],
        ['a loop that may not run', `for (let k, v in event.properties) { return event }`],
        ['only a function declaration', `fun tag(e) { return e }`],
    ])('is true for %s', async (_, code) => {
        expect(await canFinishWithoutReturn(code)).toBe(true)
    })

    test.each([
        ['a final return', `event.properties.x := 1\nreturn event`],
        ['a bare final return', `return`],
        ['an if/else that returns in every branch', `if (a) return event else return null`],
        [
            'an else-if chain with a final else',
            `if (a) { return event } else if (b) { return event } else { return event }`,
        ],
        ['a try/catch that returns in both', `try { return event } catch (e) { return event }`],
        ['a throw', `if (a) { return event } else { throw Error('nope') }`],
        ['an if on a constant true', `if (true) return event`],
        ['an endless while loop', `while (true) { return event }`],
        ['an endless for loop', `for (; true;) { return event }`],
        ['blank code', `  // nothing yet\n`],
        ['code that does not parse', `if (`],
    ])('is false for %s', async (_, code) => {
        expect(await canFinishWithoutReturn(code)).toBe(false)
    })
})
