import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DefaultEvaluationContextsResponse, defaultEvaluationContextsLogic } from './defaultEvaluationContextsLogic'

describe('defaultEvaluationContextsLogic', () => {
    let logic: ReturnType<typeof defaultEvaluationContextsLogic.build>
    let mockResponse: DefaultEvaluationContextsResponse

    beforeEach(() => {
        mockResponse = {
            default_evaluation_contexts: [],
            available_contexts: [],
            hidden_contexts: [],
            enabled: false,
        }

        useMocks({
            get: {
                '/api/environments/:team_id/default_evaluation_contexts/': () => [200, mockResponse],
            },
            post: {
                '/api/environments/:team_id/default_evaluation_contexts/': async (req) => {
                    const body = await req.json()
                    const contextName = body.context_name
                    const newContext = {
                        id: Math.floor(Math.random() * 10000),
                        name: contextName,
                    }
                    mockResponse.default_evaluation_contexts.push(newContext)
                    if (!mockResponse.available_contexts.includes(contextName)) {
                        mockResponse.available_contexts.push(contextName)
                        mockResponse.available_contexts.sort()
                    }
                    return [200, { ...newContext, created: true }]
                },
                '/api/environments/:team_id/evaluation_context_suggestions/': async (req) => {
                    const body = await req.json()
                    const contextName = body.context_name
                    mockResponse.available_contexts = mockResponse.available_contexts.filter((c) => c !== contextName)
                    if (!mockResponse.hidden_contexts.includes(contextName)) {
                        mockResponse.hidden_contexts.push(contextName)
                        mockResponse.hidden_contexts.sort()
                    }
                    return [200, { success: true, name: contextName, hidden_from_suggestions: true }]
                },
            },
            delete: {
                '/api/environments/:team_id/default_evaluation_contexts/': (req) => {
                    const contextName = req.url.searchParams.get('context_name')
                    mockResponse.default_evaluation_contexts = mockResponse.default_evaluation_contexts.filter(
                        (c) => c.name !== contextName
                    )
                    return [200, { success: true }]
                },
                '/api/environments/:team_id/evaluation_context_suggestions/': (req) => {
                    const contextName = req.url.searchParams.get('context_name')
                    mockResponse.hidden_contexts = mockResponse.hidden_contexts.filter((c) => c !== contextName)
                    if (contextName && !mockResponse.available_contexts.includes(contextName)) {
                        mockResponse.available_contexts.push(contextName)
                        mockResponse.available_contexts.sort()
                    }
                    return [200, { success: true, name: contextName, hidden_from_suggestions: false }]
                },
            },
            patch: {
                '/api/environments/:team_id/': async (req) => {
                    const body = await req.json()
                    return [200, { ...body }]
                },
            },
        })

        initKeaTests()
        logic = defaultEvaluationContextsLogic()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('loading default evaluation contexts', () => {
        it('should load empty state initially', async () => {
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadDefaultEvaluationContexts', 'loadDefaultEvaluationContextsSuccess'])
                .toMatchValues({
                    defaultEvaluationContexts: {
                        default_evaluation_contexts: [],
                        available_contexts: [],
                        hidden_contexts: [],
                        enabled: false,
                    },
                    contexts: [],
                    isEnabled: false,
                })
        })
    })

    describe('hiding and restoring suggestions', () => {
        it('should hide a context from suggestions', async () => {
            mockResponse.available_contexts = ['production', 'staging']

            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationContextsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.hideContext('production')
            })
                .toDispatchActions(['hideContext', 'hideContextSuccess'])
                .toMatchValues({
                    availableContexts: ['staging'],
                    hiddenContexts: ['production'],
                })
        })

        it('should restore a hidden context to suggestions', async () => {
            mockResponse.available_contexts = ['staging']
            mockResponse.hidden_contexts = ['production']

            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationContextsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.unhideContext('production')
            })
                .toDispatchActions(['unhideContext', 'unhideContextSuccess'])
                .toMatchValues({
                    availableContexts: ['production', 'staging'],
                    hiddenContexts: [],
                })
        })

        it('should leave availableContexts unchanged when hideContext API call fails', async () => {
            mockResponse.available_contexts = ['production', 'staging']

            useMocks({
                post: {
                    '/api/environments/:team_id/evaluation_context_suggestions/': () => [400, { error: 'Bad request' }],
                },
            })

            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationContextsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.hideContext('production')
            })
                .toDispatchActions(['hideContext', 'hideContextFailure'])
                .toMatchValues({
                    availableContexts: ['production', 'staging'],
                    hiddenContexts: [],
                })
        })
    })

    describe('adding contexts', () => {
        it('should add a new context', async () => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.addContext('production')
            })
                .toDispatchActions(['addContext', 'addContextSuccess'])
                .toMatchValues({
                    contexts: [{ id: expect.any(Number), name: 'production' }],
                })
        })

        it('should clear input after adding context', async () => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setNewContextInput('production')
            }).toMatchValues({
                newContextInput: 'production',
            })

            await expectLogic(logic, () => {
                logic.actions.addContext('production')
            }).toMatchValues({
                newContextInput: '',
            })
        })
    })

    describe('removing contexts', () => {
        it('should remove a context', async () => {
            mockResponse.default_evaluation_contexts = [
                { id: 1, name: 'production' },
                { id: 2, name: 'staging' },
            ]

            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationContextsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.removeContext('production')
            })
                .toDispatchActions(['removeContext', 'removeContextSuccess'])
                .toMatchValues({
                    contexts: [{ id: 2, name: 'staging' }],
                })
        })
    })

    describe('toggling enabled state', () => {
        it('should update team settings when toggling', async () => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleEnabled(true)
            }).toDispatchActions(['toggleEnabled', teamLogic.actionTypes.updateCurrentTeam])
        })
    })

    describe('selectors', () => {
        it('should correctly determine if more contexts can be added', async () => {
            mockResponse.default_evaluation_contexts = Array.from({ length: 9 }, (_, i) => ({
                id: i,
                name: `ctx-${i}`,
            }))

            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationContextsSuccess']).toMatchValues({
                canAddMoreContexts: true,
            })

            await expectLogic(logic, () => {
                logic.actions.addContext('ctx-9')
            })
                .toDispatchActions(['addContextSuccess'])
                .toMatchValues({
                    canAddMoreContexts: false,
                })
        })
    })
})
