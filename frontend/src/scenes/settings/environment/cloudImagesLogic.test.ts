import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

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
    let releaseBuild: () => void
    let buildResponse: [number, unknown]

    const useMountedLogicWith = (listResponse: unknown): void => {
        createBody = null
        const buildGate = new Promise<void>((resolve) => {
            releaseBuild = resolve
        })
        useMocks({
            get: { '/api/projects/:team/sandbox_custom_images/': listResponse as any },
            post: {
                '/api/projects/:team/sandbox_custom_images/:id/build/': async () => {
                    await buildGate
                    return buildResponse
                },
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

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

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

    test.each([
        ['draft', null],
        ['ready', null],
        ['scan_failed', null],
        ['build_failed', null],
        ['scanning', 'The image is being checked'],
        ['building', 'The image is being built'],
    ])('disables the build for a %s image with %p', async (status, reason) => {
        useMountedLogicWith({ count: 0, results: [] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.buildDisabledReason({ ...IMAGE, status })).toEqual(reason)
    })

    it('starts a build, shows the new status, and refreshes until the build settles', async () => {
        let listCalls = 0
        useMountedLogicWith(() => {
            listCalls += 1
            return [200, { count: 1, results: [{ ...IMAGE, status: listCalls === 1 ? 'draft' : 'ready' }] }]
        })
        await expectLogic(logic).toFinishAllListeners()
        buildResponse = [200, { ...IMAGE, status: 'scanning' }]

        logic.actions.buildImage(logic.values.images![0])
        expect(logic.values.buildDisabledReason(logic.values.images![0])).toEqual('Starting the build')

        jest.useFakeTimers()
        releaseBuild()
        await expectLogic(logic).toDispatchActions(['buildImageDone']).toFinishAllListeners()
        expect(logic.values.images?.[0].status).toEqual('scanning')
        expect(logic.values.buildingImageIds).toEqual([])

        jest.advanceTimersByTime(5000)
        await expectLogic(logic).toDispatchActions(['loadImages', 'loadImagesSuccess']).toFinishAllListeners()
        expect(logic.values.images?.[0].status).toEqual('ready')

        jest.advanceTimersByTime(5000)
        expect(listCalls).toEqual(2)
    })

    it('shows the server message when a build cannot start', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        useMountedLogicWith({ count: 1, results: [{ ...IMAGE, status: 'draft' }] })
        await expectLogic(logic).toFinishAllListeners()
        buildResponse = [400, { detail: 'The builder session has no sandbox yet; send it a message first' }]

        releaseBuild()
        await expectLogic(logic, () => logic.actions.buildImage(logic.values.images![0])).toFinishAllListeners()

        expect(toastError).toHaveBeenCalledWith('The builder session has no sandbox yet; send it a message first')
        expect(logic.values.images?.[0].status).toEqual('draft')
        expect(logic.values.buildingImageIds).toEqual([])
    })

    it('stays silent when the page closes before the build request returns', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        useMountedLogicWith({ count: 1, results: [{ ...IMAGE, status: 'draft' }] })
        await expectLogic(logic).toFinishAllListeners()
        buildResponse = [200, { ...IMAGE, status: 'scanning' }]

        logic.actions.buildImage(logic.values.images![0])
        logic.unmount()
        releaseBuild()
        await expectLogic(logic).toFinishAllListeners()

        expect(toastError).not.toHaveBeenCalled()
        logic.mount()
    })
})
