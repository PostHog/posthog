import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    DefaultEvaluationEnvironmentsResponse,
    defaultEvaluationEnvironmentsLogic,
} from './defaultEvaluationEnvironmentsLogic'

describe('defaultEvaluationEnvironmentsLogic', () => {
    let logic: ReturnType<typeof defaultEvaluationEnvironmentsLogic.build>
    let mockResponse: DefaultEvaluationEnvironmentsResponse

    beforeEach(() => {
        mockResponse = {
            default_evaluation_tags: [],
            enabled: false,
        }

        useMocks({
            get: {
                '/api/environments/:team_id/default_evaluation_tags/': () => [200, mockResponse],
            },
            post: {
                '/api/environments/:team_id/default_evaluation_tags/': async (req) => {
                    const body = await req.json()
                    const tagName = body.tag_name
                    const newTag = {
                        id: Math.floor(Math.random() * 10000),
                        name: tagName,
                    }
                    mockResponse.default_evaluation_tags.push(newTag)
                    return [200, { ...newTag, created: true }]
                },
            },
            delete: {
                '/api/environments/:team_id/default_evaluation_tags/': (req) => {
                    const tagName = req.url.searchParams.get('tag_name')
                    mockResponse.default_evaluation_tags = mockResponse.default_evaluation_tags.filter(
                        (t) => t.name !== tagName
                    )
                    return [200, { success: true }]
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
        logic = defaultEvaluationEnvironmentsLogic()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('loading default evaluation environments', () => {
        it('should load empty state initially', async () => {
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadDefaultEvaluationEnvironments', 'loadDefaultEvaluationEnvironmentsSuccess'])
                .toMatchValues({
                    defaultEvaluationEnvironments: {
                        default_evaluation_tags: [],
                        enabled: false,
                    },
                    tags: [],
                    isEnabled: false,
                })
        })
    })

    describe('adding tags', () => {
        it('should add a new tag', async () => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.addTag('production')
            })
                .toDispatchActions(['addTag', 'addTagSuccess'])
                .toMatchValues({
                    tags: [{ id: expect.any(Number), name: 'production' }],
                })
        })

        it('should clear input after adding tag', async () => {
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setNewTagInput('production')
            }).toMatchValues({
                newTagInput: 'production',
            })

            await expectLogic(logic, () => {
                logic.actions.addTag('production')
            }).toMatchValues({
                newTagInput: '',
            })
        })
    })

    describe('removing tags', () => {
        it('should remove a tag', async () => {
            mockResponse.default_evaluation_tags = [
                { id: 1, name: 'production' },
                { id: 2, name: 'staging' },
            ]

            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationEnvironmentsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.removeTag('production')
            })
                .toDispatchActions(['removeTag', 'removeTagSuccess'])
                .toMatchValues({
                    tags: [{ id: 2, name: 'staging' }],
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
        it('should correctly determine if more tags can be added', async () => {
            mockResponse.default_evaluation_tags = Array.from({ length: 9 }, (_, i) => ({ id: i, name: `tag-${i}` }))

            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationEnvironmentsSuccess']).toMatchValues({
                canAddMoreTags: true,
            })

            await expectLogic(logic, () => {
                logic.actions.addTag('tag-9')
            })
                .toDispatchActions(['addTagSuccess'])
                .toMatchValues({
                    canAddMoreTags: false,
                })
        })
    })
})
