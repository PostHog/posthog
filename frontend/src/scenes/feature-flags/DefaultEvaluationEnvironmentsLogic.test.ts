import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { defaultEvaluationEnvironmentsLogic } from './DefaultEvaluationEnvironmentsLogic'

describe('defaultEvaluationEnvironmentsLogic', () => {
    let logic: ReturnType<typeof defaultEvaluationEnvironmentsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:id/default_evaluation_tags/': {
                    default_evaluation_tags: [],
                    enabled: false,
                },
            },
            post: {
                '/api/projects/:id/default_evaluation_tags/': (req) => {
                    const tagName = req.body.tag_name
                    return [
                        200,
                        {
                            id: Math.random(),
                            name: tagName,
                            created: true,
                        },
                    ]
                },
            },
            delete: {
                '/api/projects/:id/default_evaluation_tags/': () => {
                    return [200, { success: true }]
                },
            },
        })

        initKeaTests()
        logic = defaultEvaluationEnvironmentsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('loading default evaluation environments', () => {
        it('should load empty state initially', async () => {
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

        it('should load existing tags', async () => {
            useMocks({
                get: {
                    '/api/projects/:id/default_evaluation_tags/': {
                        default_evaluation_tags: [
                            { id: 1, name: 'production' },
                            { id: 2, name: 'staging' },
                        ],
                        enabled: true,
                    },
                },
            })

            logic = defaultEvaluationEnvironmentsLogic()
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadDefaultEvaluationEnvironments', 'loadDefaultEvaluationEnvironmentsSuccess'])
                .toMatchValues({
                    tags: [
                        { id: 1, name: 'production' },
                        { id: 2, name: 'staging' },
                    ],
                })
        })
    })

    describe('adding tags', () => {
        it('should add a new tag', async () => {
            await expectLogic(logic, () => {
                logic.actions.addTag('production')
            })
                .toDispatchActions(['addTag', 'addTagSuccess'])
                .toMatchValues({
                    tags: [{ id: expect.any(Number), name: 'production' }],
                })
        })

        it('should handle duplicate tags gracefully', async () => {
            useMocks({
                post: {
                    '/api/projects/:id/default_evaluation_tags/': () => {
                        return [
                            200,
                            {
                                id: 1,
                                name: 'production',
                                created: false, // Not created because it already exists
                            },
                        ]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.addTag('production')
            })
                .toDispatchActions(['addTag', 'addTagSuccess'])
                .toMatchValues({
                    tags: [], // Should not add duplicate
                })
        })

        it('should show error when adding tag fails', async () => {
            useMocks({
                post: {
                    '/api/projects/:id/default_evaluation_tags/': () => {
                        return [400, { error: 'Maximum of 10 default evaluation tags allowed' }]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.addTag('eleventh-tag')
            }).toDispatchActions(['addTag', 'addTagFailure'])
        })
    })

    describe('removing tags', () => {
        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/projects/:id/default_evaluation_tags/': {
                        default_evaluation_tags: [
                            { id: 1, name: 'production' },
                            { id: 2, name: 'staging' },
                        ],
                        enabled: false,
                    },
                },
            })

            logic = defaultEvaluationEnvironmentsLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationEnvironmentsSuccess'])
        })

        it('should remove a tag', async () => {
            await expectLogic(logic, () => {
                logic.actions.removeTag('production')
            })
                .toDispatchActions(['removeTag', 'removeTagSuccess'])
                .toMatchValues({
                    tags: [{ id: 2, name: 'staging' }],
                })
        })

        it('should handle removing non-existent tag', async () => {
            useMocks({
                delete: {
                    '/api/projects/:id/default_evaluation_tags/': () => {
                        return [404, { error: 'Tag not found' }]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.removeTag('nonexistent')
            }).toDispatchActions(['removeTag', 'removeTagFailure'])
        })
    })

    describe('toggling enabled state', () => {
        it('should update team settings when toggling', async () => {
            const teamLogicInstance = teamLogic()
            teamLogicInstance.mount()

            await expectLogic(logic, () => {
                logic.actions.toggleEnabled(true)
            }).toDispatchActions([teamLogicInstance, 'updateCurrentTeam'])

            teamLogicInstance.unmount()
        })
    })

    describe('selectors', () => {
        it('should correctly determine if more tags can be added', async () => {
            // Start with 9 tags
            const tags = Array.from({ length: 9 }, (_, i) => ({ id: i, name: `tag-${i}` }))

            useMocks({
                get: {
                    '/api/projects/:id/default_evaluation_tags/': {
                        default_evaluation_tags: tags,
                        enabled: false,
                    },
                },
            })

            logic = defaultEvaluationEnvironmentsLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadDefaultEvaluationEnvironmentsSuccess']).toMatchValues({
                canAddMoreTags: true,
            })

            // Add 10th tag
            useMocks({
                post: {
                    '/api/projects/:id/default_evaluation_tags/': () => {
                        return [
                            200,
                            {
                                id: 10,
                                name: 'tag-10',
                                created: true,
                            },
                        ]
                    },
                },
            })

            await expectLogic(logic, () => {
                logic.actions.addTag('tag-10')
            })
                .toDispatchActions(['addTagSuccess'])
                .toMatchValues({
                    canAddMoreTags: false,
                })
        })
    })

    describe('input management', () => {
        it('should clear input after adding tag', async () => {
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
})
