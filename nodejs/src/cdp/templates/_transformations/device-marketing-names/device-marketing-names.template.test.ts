import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './device-marketing-names.template'

describe('device-marketing-names.template', () => {
    // A generous budget so a loaded CI runner can't turn a slow run into a false failure.
    const tester = new TemplateTester(template, { executionTimeoutMs: 10_000 })
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke({}, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as any
    }

    it('leaves the event unchanged when $device_model is absent', async () => {
        mockGlobals = tester.createGlobals({
            event: { properties: { unrelated: 'x' } },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual({ unrelated: 'x' })
    })

    it.each([
        ['a number', 12],
        ['an empty string', ''],
        ['an unknown Apple identifier', 'iPhone99,9'],
        ['an unrecognized model', 'not-a-device'],
    ])('does not add $device_marketing_name when $device_model is %s', async (_, deviceModel) => {
        mockGlobals = tester.createGlobals({
            event: { properties: { $device_model: deviceModel } },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual({ $device_model: deviceModel })
    })

    it.each([
        ['a native macOS app on Apple silicon', { $device_model: 'arm64', $os_name: 'macOS' }],
        ['a native macOS app on Intel', { $device_model: 'x86_64', $os_name: 'macOS' }],
        ['a Windows client reporting its CPU', { $device_model: 'x86_64', $os_name: 'Windows' }],
        ['a CPU architecture without the simulator flag', { $device_model: 'arm64' }],
        ['an event that already has a name', { $device_model: 'iPhone15,2', $device_marketing_name: 'My test phone' }],
    ])('leaves the event unchanged for %s', async (_, properties) => {
        mockGlobals = tester.createGlobals({
            event: { properties },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual(properties)
    })

    it.each([
        ['an iPhone simulator', { $device_model: 'arm64', $os_name: 'iOS', $is_emulator: true }],
        ['an iPad simulator', { $device_model: 'arm64', $os_name: 'iPadOS', $is_emulator: true }],
        ['a simulator on an Intel Mac', { $device_model: 'x86_64', $os_name: 'iOS', $is_emulator: true }],
    ])('labels %s as Simulator', async (_, properties) => {
        mockGlobals = tester.createGlobals({
            event: { properties },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual({ ...properties, $device_marketing_name: 'Simulator' })
    })

    it.each([
        ['iPhone15,2', 'iPhone 14 Pro'],
        ['iPad13,18', 'iPad (10th generation)'],
    ])('maps %s to %s and keeps the raw identifier', async (deviceModel, name) => {
        mockGlobals = tester.createGlobals({
            event: { properties: { $device_model: deviceModel } },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual({ $device_model: deviceModel, $device_marketing_name: name })
    })
})
