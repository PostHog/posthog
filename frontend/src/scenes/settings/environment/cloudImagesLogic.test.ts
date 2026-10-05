import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { cloudImagesLogic } from './cloudImagesLogic'

const IMAGE = {
    id: '0190e5a3-0000-7000-8000-0000000000a1',
    name: 'Node 22',
    description: 'Node 22 and pnpm',
    status: 'ready',
    version: 1,
    modal_image_name: 'img:1',
    error: '',
    private: true,
    builder_task_id: '0190e5a3-0000-7000-8000-0000000000b1',
}

describe('cloudImagesLogic', () => {
    let logic: ReturnType<typeof cloudImagesLogic.build>
    let createBody: Record<string, unknown> | null

    const useMountedLogicWith = (listResponse: unknown): void => {
        createBody = null
        useMocks({
            get: { '/api/projects/:team/sandbox_custom_images/': listResponse as any },
            post: {
                '/api/projects/:team/sandbox_custom_images/': async ({ request }) => {
                    createBody = (await request.json()) as Record<string, unknown>
                    return [201, { ...IMAGE, id: 'new', builder_task_id: 'builder-task', ...createBody }]
                },
            },
        })
        initKeaTests()
        logic = cloudImagesLogic()
        logic.mount()
    }

    afterEach(() => logic.unmount())

    it('marks custom images as unavailable when the project cannot use them', async () => {
        useMountedLogicWith(() => [
            403,
            { detail: 'Custom sandbox images require the Modal VM runtime, which is not enabled' },
        ])

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.unavailable).toBe(true)
        expect(logic.values.imagesFailed).toBe(false)
    })

    it('hides archived images', async () => {
        useMountedLogicWith({ count: 2, results: [IMAGE, { ...IMAGE, id: 'old', status: 'archived' }] })

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.images?.map((image) => image.id)).toEqual([IMAGE.id])
    })

    it('creates an image and opens its builder task', async () => {
        useMountedLogicWith({ count: 0, results: [] })
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startNewImage()
        logic.actions.updateDraft({ name: ' Node 22 ', description: 'Node 22 and pnpm', repository: 'example/web' })
        await expectLogic(logic, () => logic.actions.createImage()).toFinishAllListeners()

        expect(createBody).toEqual({
            name: 'Node 22',
            description: 'Node 22 and pnpm',
            repository: 'example/web',
            private: true,
        })
        expect(router.values.location.pathname).toContain('/tasks/builder-task')
        expect(logic.values.draft).toBeNull()
    })
})
