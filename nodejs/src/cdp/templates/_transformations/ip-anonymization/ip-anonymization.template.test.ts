import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './ip-anonymization.template'

describe('ip-anonymization.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should anonymize IPv4 address by zeroing last octet', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    $ip: '89.160.20.129',
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {
                $ip: '89.160.20.0',
            },
        })
    })

    it('should handle event with no IP address', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                properties: {},
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toMatchObject({
            properties: {},
        })
    })

    it('should handle invalid IP address format', async () => {
        const invalidIPs = [
            '89.160.20', // missing octet
            '', // empty string
            'abc.def.ghi.jkl', // non-numeric
            '256.256.256.256', // values > 255
            '1.2.3.4.5', // too many octets
            'not an ip',
        ]

        for (const invalidIP of invalidIPs) {
            mockGlobals = tester.createGlobals({
                event: {
                    properties: {
                        $ip: invalidIP,
                    },
                },
            })

            const response = await tester.invoke({}, mockGlobals)

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).toMatchObject({
                properties: {
                    $ip: invalidIP,
                },
            })
        }
    })

    it('should handle various IPv4 formats', async () => {
        const testCases = [
            { input: '192.168.1.1', expected: '192.168.1.0' },
            { input: '10.0.0.255', expected: '10.0.0.0' },
            { input: '172.16.254.1', expected: '172.16.254.0' },
        ]

        for (const testCase of testCases) {
            mockGlobals = tester.createGlobals({
                event: {
                    properties: {
                        $ip: testCase.input,
                    },
                },
            })

            const response = await tester.invoke({}, mockGlobals)

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).toMatchObject({
                properties: {
                    $ip: testCase.expected,
                },
            })
        }
    })
})
