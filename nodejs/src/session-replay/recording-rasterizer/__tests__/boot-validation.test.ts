/**
 * boot-validation runs before the worker connects to Temporal, so its failure
 * modes need to be unambiguous: bad config crashes the process, good config
 * proceeds silently.
 *
 * isProdEnv() is mocked rather than NODE_ENV-twiddled, because the surrounding
 * test harness force-restores NODE_ENV between hooks.
 */
import { isProdEnv } from '../../../utils/env-utils'
import { validateBootEnvironment } from '../boot-validation'

jest.mock('../../../utils/env-utils', () => ({
    ...jest.requireActual('../../../utils/env-utils'),
    isProdEnv: jest.fn(),
}))

const mockedIsProdEnv = isProdEnv as jest.MockedFunction<typeof isProdEnv>

const originalDisable = process.env.DISABLE_BROWSER_SECURITY
const originalRules = process.env.CHROME_HOST_RESOLVER_RULES

function setEnv(name: string, value: string | undefined): void {
    if (value === undefined) {
        delete process.env[name]
    } else {
        process.env[name] = value
    }
}

afterEach(() => {
    setEnv('DISABLE_BROWSER_SECURITY', originalDisable)
    setEnv('CHROME_HOST_RESOLVER_RULES', originalRules)
})

describe('validateBootEnvironment', () => {
    describe('in production', () => {
        beforeEach(() => {
            mockedIsProdEnv.mockReturnValue(true)
        })

        it('passes when no debug flags are set', () => {
            setEnv('DISABLE_BROWSER_SECURITY', undefined)
            setEnv('CHROME_HOST_RESOLVER_RULES', undefined)
            expect(() => validateBootEnvironment()).not.toThrow()
        })

        it('throws when DISABLE_BROWSER_SECURITY=1', () => {
            setEnv('DISABLE_BROWSER_SECURITY', '1')
            setEnv('CHROME_HOST_RESOLVER_RULES', undefined)
            expect(() => validateBootEnvironment()).toThrow(/DISABLE_BROWSER_SECURITY is set in a production/)
        })

        it('throws when CHROME_HOST_RESOLVER_RULES is set', () => {
            setEnv('DISABLE_BROWSER_SECURITY', undefined)
            setEnv('CHROME_HOST_RESOLVER_RULES', 'MAP localhost host.docker.internal')
            expect(() => validateBootEnvironment()).toThrow(/CHROME_HOST_RESOLVER_RULES is set in a production/)
        })
    })

    describe('in development', () => {
        beforeEach(() => {
            mockedIsProdEnv.mockReturnValue(false)
        })

        it('allows DISABLE_BROWSER_SECURITY=1', () => {
            setEnv('DISABLE_BROWSER_SECURITY', '1')
            setEnv('CHROME_HOST_RESOLVER_RULES', undefined)
            expect(() => validateBootEnvironment()).not.toThrow()
        })

        it('allows well-formed CHROME_HOST_RESOLVER_RULES', () => {
            setEnv('DISABLE_BROWSER_SECURITY', undefined)
            setEnv('CHROME_HOST_RESOLVER_RULES', 'MAP localhost host.docker.internal, EXCLUDE *.example.com')
            expect(() => validateBootEnvironment()).not.toThrow()
        })

        it.each([
            ['shell-character in hostname', 'MAP localhost host;rm-rf'],
            ['unknown verb', 'PROXY localhost 127.0.0.1'],
            ['missing operand', 'MAP localhost'],
            ['embedded space in operand', 'MAP "evil host" 127.0.0.1'],
        ])('rejects malformed CHROME_HOST_RESOLVER_RULES (%s)', (_, value) => {
            setEnv('DISABLE_BROWSER_SECURITY', undefined)
            setEnv('CHROME_HOST_RESOLVER_RULES', value)
            expect(() => validateBootEnvironment()).toThrow(/CHROME_HOST_RESOLVER_RULES/)
        })
    })
})
