import crypto from 'crypto'

import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './secure-events.template'

interface EventResult {
    distinct_id?: string
    properties: {
        $verified_distinct_id?: boolean
        [key: string]: any
    }
}

describe('secure-events.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    const generateHash = (secret: string, distinctId: string): string => {
        return crypto.createHmac('sha256', secret).update(distinctId).digest('hex')
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    describe('validation with primary secret', () => {
        it('should mark event as verified when hash is valid', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should mark event as unverified when hash is invalid', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const invalidHash = 'invalid-hash'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: invalidHash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })

        it('should support distinct_id_hash property name without $ prefix', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })
    })

    describe('validation with secondary secret (key rotation)', () => {
        it('should validate against secondary secret when primary fails', async () => {
            const distinctId = 'user123'
            const primarySecret = 'old-secret'
            const secondarySecret = 'new-secret'
            const hash = generateHash(secondarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    secondarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should validate against primary secret when both are provided', async () => {
            const distinctId = 'user123'
            const primarySecret = 'primary-secret'
            const secondarySecret = 'secondary-secret'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    secondarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should mark as unverified when hash matches neither secret', async () => {
            const distinctId = 'user123'
            const primarySecret = 'primary-secret'
            const secondarySecret = 'secondary-secret'
            const wrongSecret = 'wrong-secret'
            const hash = generateHash(wrongSecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    secondarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })
    })

    describe('enforce secure mode', () => {
        it('should drop event when validation fails and enforce mode is enabled', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const invalidHash = 'invalid-hash'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: invalidHash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: true,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).toBeUndefined()
        })

        it('should not drop event when validation succeeds even with enforce mode enabled', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: true,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).not.toBeNull()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should drop event when no hash provided and enforce mode is enabled', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {},
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: true,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).toBeUndefined()
        })

        it('should drop event when no distinct_id provided and enforce mode is enabled', async () => {
            const primarySecret = 'my-secret-key'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: '',
                    properties: {
                        $distinct_id_hash: 'some-hash',
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: true,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect(response.execResult).toBeUndefined()
        })
    })

    describe('edge cases', () => {
        it('should mark as unverified when distinct_id is missing', async () => {
            const primarySecret = 'my-secret-key'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: '',
                    properties: {
                        $distinct_id_hash: 'some-hash',
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: false,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })

        it('should mark as unverified when hash is missing', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {},
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                    enforceSecureMode: false,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })

        it('should handle numeric distinct_id correctly', async () => {
            const distinctId = 12345
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId.toString())

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId as any,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should preserve other event properties', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                        custom_property: 'custom_value',
                        $lib: 'web',
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            const result = response.execResult as EventResult
            expect(result.properties.$verified_distinct_id).toBe(true)
            expect(result.properties.custom_property).toBe('custom_value')
            expect(result.properties.$lib).toBe('web')
            expect(result.properties.$distinct_id_hash).toBe(hash)
        })

        it('should handle empty properties object', async () => {
            const distinctId = 'user123'
            const primarySecret = 'my-secret-key'

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: undefined as any,
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })

        it('should validate correctly with special characters in distinct_id', async () => {
            const distinctId = 'user+test@example.com'
            const primarySecret = 'my-secret-key'
            const hash = generateHash(primarySecret, distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(true)
        })

        it('should be case-sensitive for secrets', async () => {
            const distinctId = 'user123'
            const primarySecret = 'MySecret'
            const hash = generateHash('mySecret', distinctId)

            mockGlobals = tester.createGlobals({
                event: {
                    distinct_id: distinctId,
                    properties: {
                        $distinct_id_hash: hash,
                    },
                },
            })

            const response = await tester.invoke(
                {
                    primarySecret,
                },
                mockGlobals
            )

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
            expect((response.execResult as EventResult).properties.$verified_distinct_id).toBe(false)
        })
    })
})
