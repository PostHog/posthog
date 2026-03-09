import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../../_tests/fixtures'
import { createInvocation } from '../../utils/invocation-utils'
import { sanitizeInvocationForPersistence } from './shared'

describe('sanitizeInvocationForPersistence', () => {
    const exampleHogFunction = createHogFunction({
        name: 'Test hog function',
        ...HOG_EXAMPLES.simple_fetch,
        ...HOG_INPUTS_EXAMPLES.simple_fetch,
        ...HOG_FILTERS_EXAMPLES.no_filters,
    })

    it('should strip groups from state.globals', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({
                    groups: {
                        organization: {
                            id: 'org-1',
                            type: 'organization',
                            index: 0,
                            url: 'http://localhost:8000/groups/0/org-1',
                            properties: { name: 'PostHog', employee_count: 100 },
                        },
                    },
                }),
                inputs: {},
            },
            exampleHogFunction
        )

        expect(invocation.state.globals.groups).toBeDefined()

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.groups).toBeUndefined()
        // Original should not be mutated
        expect(invocation.state.globals.groups).toBeDefined()
    })

    it('should preserve all other state fields', () => {
        const globals = {
            ...createHogExecutionGlobals({
                groups: {
                    organization: {
                        id: 'org-1',
                        type: 'organization',
                        index: 0,
                        url: 'http://localhost:8000/groups/0/org-1',
                        properties: { name: 'PostHog' },
                    },
                },
            }),
            inputs: { url: 'https://example.com' },
        }
        const invocation = createInvocation(globals, exampleHogFunction)

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.event).toEqual(invocation.state.globals.event)
        expect(sanitized.state!.globals.person).toEqual(invocation.state.globals.person)
        expect(sanitized.state!.globals.project).toEqual(invocation.state.globals.project)
        expect(sanitized.state!.globals.inputs).toEqual(invocation.state.globals.inputs)
        expect(sanitized.state!.timings).toEqual(invocation.state.timings)
        expect(sanitized.teamId).toEqual(invocation.teamId)
        expect(sanitized.functionId).toEqual(invocation.functionId)
    })

    it('should return original invocation when no groups present', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({ groups: undefined }),
                inputs: {},
            },
            exampleHogFunction
        )
        delete invocation.state.globals.groups

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should return original invocation when groups is empty', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals(),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should handle invocations without state.globals (e.g. hogflow)', () => {
        const invocation = {
            id: 'test-id',
            teamId: 1,
            functionId: 'func-1',
            queue: 'hogflow' as const,
            queuePriority: 0,
            state: {
                event: {
                    uuid: 'test',
                    event: 'test',
                    distinct_id: 'test',
                    properties: {},
                    elements_chain: '',
                    timestamp: '',
                    url: '',
                },
                actionStepCount: 0,
            },
        }

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized).toBe(invocation)
    })

    it('should strip multiple group types', () => {
        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals({
                    groups: {
                        organization: {
                            id: 'org-1',
                            type: 'organization',
                            index: 0,
                            url: 'http://localhost:8000/groups/0/org-1',
                            properties: { name: 'PostHog', employee_count: 100, plan: 'enterprise' },
                        },
                        company: {
                            id: 'company-1',
                            type: 'company',
                            index: 1,
                            url: 'http://localhost:8000/groups/1/company-1',
                            properties: { name: 'Acme Inc', revenue: 1000000 },
                        },
                    },
                }),
                inputs: {},
            },
            exampleHogFunction
        )

        const sanitized = sanitizeInvocationForPersistence(invocation)

        expect(sanitized.state!.globals.groups).toBeUndefined()
        expect(sanitized.state!.globals.event).toBeDefined()

        // Original retains both groups
        expect(Object.keys(invocation.state.globals.groups!)).toEqual(['organization', 'company'])
    })
})
