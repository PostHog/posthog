import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './user-agent.template'

const CHROME_UA =
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
const IPHONE_UA =
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'

describe('user-agent.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as any
    }

    it('populates browser and device properties from a desktop user agent', async () => {
        const globals = tester.createGlobals({ event: { properties: { $useragent: CHROME_UA } } })

        const result = await invoke({}, globals)

        expect(result.properties.$browser).toBe('chrome')
        expect(result.properties.$browser_version).toBe('120.0.0')
        expect(result.properties.$os).toBe('Mac OS')
        expect(result.properties.$browser_type).toBe('browser')
        expect(result.properties.$device).toBe('')
        expect(result.properties.$device_type).toBe('Desktop')
        // The raw user agent value is stripped once parsed.
        expect(result.properties.$useragent).toBeNull()
    })

    it('detects a mobile device and reads the $user-agent key', async () => {
        const globals = tester.createGlobals({ event: { properties: { '$user-agent': IPHONE_UA } } })

        const result = await invoke({}, globals)

        expect(result.properties.$device).toBe('iPhone')
        expect(result.properties.$device_type).toBe('Mobile')
        expect(result.properties.$os).toBe('iOS')
    })

    it('reads $raw_user_agent and leaves it in place', async () => {
        const globals = tester.createGlobals({ event: { properties: { $raw_user_agent: IPHONE_UA } } })

        const result = await invoke({}, globals)

        expect(result.properties.$device).toBe('iPhone')
        expect(result.properties.$device_type).toBe('Mobile')
        expect(result.properties.$os).toBe('iOS')
        // Bot detection and the ad destinations read this property after this transformation.
        expect(result.properties.$raw_user_agent).toBe(IPHONE_UA)
    })

    it('skips an empty alias and reads the next populated one', async () => {
        const globals = tester.createGlobals({
            event: { properties: { $useragent: '', $raw_user_agent: IPHONE_UA } },
        })

        const result = await invoke({}, globals)

        expect(result.properties.$device).toBe('iPhone')
        expect(result.properties.$os).toBe('iOS')
    })

    it('does not overwrite existing browser properties by default', async () => {
        const globals = tester.createGlobals({
            event: { properties: { $useragent: CHROME_UA, $browser: 'firefox' } },
        })

        const result = await invoke({}, globals)

        expect(result.properties.$browser).toBe('firefox')
    })

    it('overwrites existing properties when overrideExisting is set', async () => {
        const globals = tester.createGlobals({
            event: { properties: { $useragent: CHROME_UA, $browser: 'firefox' } },
        })

        const result = await invoke({ overrideExisting: true }, globals)

        expect(result.properties.$browser).toBe('chrome')
    })

    it('sets no browser or device properties when there is no user agent', async () => {
        const globals = tester.createGlobals({ event: { properties: { unrelated: 'x' } } })

        const result = await invoke({}, globals)

        expect(result.properties.unrelated).toBe('x')
        expect(result.properties.$browser).toBeUndefined()
        expect(result.properties.$device).toBeUndefined()
        expect(result.properties.$device_type).toBeUndefined()
    })
})
