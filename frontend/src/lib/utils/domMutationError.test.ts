import { DOM_MUTATION_EXCEPTION_FINGERPRINT, fingerprintDOMMutationExceptions } from './domMutationError'

type TestEvent = { event?: string; properties?: Record<string, any> }

describe('fingerprintDOMMutationExceptions', () => {
    it.each([
        "Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.",
        "Failed to execute 'insertBefore' on 'Node': The node before which the new node is to be inserted is not a child.",
        "Failed to execute 'appendChild' on 'Node': something",
    ])('stamps the stable fingerprint on browser-extension DOM crashes: %s', (value) => {
        const event: TestEvent = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'NotFoundError', value }] },
        }
        expect(fingerprintDOMMutationExceptions(event).properties?.$exception_fingerprint).toBe(
            DOM_MUTATION_EXCEPTION_FINGERPRINT
        )
    })

    it('collapses hash-rotated variants onto one fingerprint regardless of chunk in the stack', () => {
        const variant = (chunk: string): TestEvent => ({
            event: '$exception',
            properties: {
                $exception_list: [
                    {
                        type: 'NotFoundError',
                        value: "Failed to execute 'removeChild' on 'Node'",
                        stacktrace: { frames: [{ filename: `https://app/${chunk}.chunk.js` }] },
                    },
                ],
            },
        })
        const a = fingerprintDOMMutationExceptions(variant('5610.166fa120'))
        const b = fingerprintDOMMutationExceptions(variant('5610.99abcd00'))
        expect(a.properties?.$exception_fingerprint).toBe(b.properties?.$exception_fingerprint)
        expect(a.properties?.$exception_fingerprint).toBe(DOM_MUTATION_EXCEPTION_FINGERPRINT)
    })

    it('leaves unrelated $exception events untouched so real bugs keep their own fingerprint', () => {
        const event: TestEvent = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(fingerprintDOMMutationExceptions(event).properties?.$exception_fingerprint).toBeUndefined()
    })

    it('does not override a fingerprint that was already set', () => {
        const event: TestEvent = {
            event: '$exception',
            properties: {
                $exception_fingerprint: 'manual-override',
                $exception_list: [{ type: 'NotFoundError', value: "Failed to execute 'removeChild' on 'Node'" }],
            },
        }
        expect(fingerprintDOMMutationExceptions(event).properties?.$exception_fingerprint).toBe('manual-override')
    })

    it.each([[null], [{ event: '$pageview', properties: { $current_url: '/foo' } }], [{ event: '$exception' }]])(
        'passes through non-matching events unchanged: %s',
        (event) => {
            expect(fingerprintDOMMutationExceptions(event as TestEvent | null)).toBe(event)
        }
    )
})
