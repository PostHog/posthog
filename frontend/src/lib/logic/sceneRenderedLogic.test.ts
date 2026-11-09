import { expectLogic } from 'kea-test-utils'

import { onFirstSceneRendered } from 'lib/utils/bootTiming'

import { initKeaTests } from '~/test/init'

import { SCENE_RENDERED_MAX_WAIT_MS, sceneRenderedLogic } from './sceneRenderedLogic'

jest.mock('lib/utils/bootTiming', () => ({ onFirstSceneRendered: jest.fn() }))

describe('sceneRenderedLogic', () => {
    let renderScene: () => void

    beforeEach(() => {
        jest.useFakeTimers()
        renderScene = () => {}
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        { name: 'when the scene renders', trigger: 'render' },
        { name: 'after the maximum wait when no scene renders', trigger: 'wait' },
        { name: 'at mount when the scene has already rendered', trigger: 'mount' },
    ])('dispatches sceneRendered once, $name', async ({ trigger }) => {
        jest.mocked(onFirstSceneRendered).mockImplementation((listener) => {
            renderScene = listener
            if (trigger === 'mount') {
                listener()
            }
            return () => {}
        })
        const logic = sceneRenderedLogic()

        await expectLogic(logic, () => {
            logic.mount()
            jest.advanceTimersByTime(SCENE_RENDERED_MAX_WAIT_MS - 1)
            expect(logic.values.sceneHasRendered).toBe(trigger === 'mount')
            if (trigger === 'render') {
                renderScene()
            } else if (trigger === 'wait') {
                jest.advanceTimersByTime(1)
            }
        })
            .toDispatchActions(['sceneRendered'])
            .toMatchValues({ sceneHasRendered: true })

        await expectLogic(logic, () => {
            jest.advanceTimersByTime(SCENE_RENDERED_MAX_WAIT_MS)
            renderScene()
        }).toNotHaveDispatchedActions(['sceneRendered'])
    })
})
