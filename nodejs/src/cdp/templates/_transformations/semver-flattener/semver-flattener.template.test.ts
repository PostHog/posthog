import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './semver-flattener.template'

describe('semver-flattener.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke(inputs, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as any
    }

    it('flattens each targeted version and leaves others untouched', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    targetted_version: '1.12.20',
                    not_a_targetted_version: '1.34.53',
                    another_targetted_version: '1.23.14-pre+build.12345',
                },
            },
        })

        const result = await invoke({ properties: 'targetted_version, another_targetted_version' }, mockGlobals)

        expect(result.properties).toEqual({
            targetted_version: '1.12.20',
            targetted_version__major: 1,
            targetted_version__minor: 12,
            targetted_version__patch: 20,
            not_a_targetted_version: '1.34.53',
            another_targetted_version: '1.23.14-pre+build.12345',
            another_targetted_version__major: 1,
            another_targetted_version__minor: 23,
            another_targetted_version__patch: 14,
            another_targetted_version__preRelease: 'pre',
            another_targetted_version__build: 'build.12345',
        })
    })

    it('handles versions with no patch, pre-release joined by dashes, and build-only', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    a: '22.7',
                    b: '22.7-pre-release',
                    c: '1.0.0+20130313144700',
                },
            },
        })

        const result = await invoke({ properties: 'a, b, c' }, mockGlobals)

        expect(result.properties.a__major).toBe(22)
        expect(result.properties.a__minor).toBe(7)
        expect(result.properties.a__patch).toBeUndefined()
        expect(result.properties.b__preRelease).toBe('pre-release')
        expect(result.properties.b__patch).toBeUndefined()
        expect(result.properties.c__patch).toBe(0)
        expect(result.properties.c__build).toBe('20130313144700')
        expect(result.properties.c__preRelease).toBeUndefined()
    })

    it('leaves the event unchanged when the target property is absent', async () => {
        mockGlobals = tester.createGlobals({
            event: { properties: { unrelated: 'x' } },
        })

        const result = await invoke({ properties: 'app_version' }, mockGlobals)

        expect(result.properties).toEqual({ unrelated: 'x' })
    })
})
