import { resetContext } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FORM_MODES } from './experimentLogic'
import { experimentSceneLogic } from './experimentSceneLogic'

type ExperimentLogicMock = {
    experimentLogic: {
        build: jest.Mock<any, any>
        __logic: {
            mount: jest.Mock<any, any>
            actions: {
                setEditExperiment: jest.Mock
                resetExperiment: jest.Mock
                loadExperiment: jest.Mock
                loadExposures: jest.Mock
            }
            props: any
            getLastUnmountFn: () => jest.Mock
        }
    }
}

jest.mock('./experimentLogic', () => {
    let unmountFn: jest.Mock
    const logicInstance = {
        mount: jest.fn(() => {
            unmountFn = jest.fn()
            return unmountFn
        }),
        actions: {
            setEditExperiment: jest.fn(),
            resetExperiment: jest.fn(),
            loadExperiment: jest.fn(),
            loadExposures: jest.fn(),
        },
        props: {},
        getLastUnmountFn: () => unmountFn,
    }

    return {
        FORM_MODES: { create: 'create', duplicate: 'duplicate', update: 'update' },
        experimentLogic: {
            build: jest.fn((props) => {
                logicInstance.props = props
                return logicInstance
            }),
            __logic: logicInstance,
        },
        NEW_EXPERIMENT: {},
    }
})

jest.mock('scenes/sceneLogic', () => ({
    sceneLogic: {
        values: {
            activeTabId: 'test-tab',
            tabs: [],
        },
        actions: {
            setTabs: jest.fn(),
        },
        isMounted: jest.fn(() => true),
    },
}))

const mockModule = require('./experimentLogic') as ExperimentLogicMock
const tabId = 'test-tab'

describe('experimentSceneLogic', () => {
    beforeEach(() => {
        resetContext({ createStore: true })
        jest.clearAllMocks()
        mockModule.experimentLogic.__logic.actions.loadExperiment.mockClear()
        mockModule.experimentLogic.__logic.actions.loadExposures.mockClear()
    })

    it('mounts experiment logic on scene state change', async () => {
        const logic = experimentSceneLogic({ tabId, experimentId: 'new', formMode: FORM_MODES.create })
        logic.mount()

        mockModule.experimentLogic.build.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setSceneState(123 as any, FORM_MODES.update)
        }).toMatchValues({
            experimentId: 123,
            formMode: FORM_MODES.update,
        })

        expect(mockModule.experimentLogic.build).toHaveBeenCalledTimes(1)
        expect(mockModule.experimentLogic.__logic.props).toMatchObject({ experimentId: 123 })

        logic.unmount()
    })

    it('does not rebuild logic when experiment id and mode stay the same', async () => {
        const logic = experimentSceneLogic({ tabId, experimentId: 456 as any, formMode: FORM_MODES.update })
        logic.mount()

        const initialBuildCount = mockModule.experimentLogic.build.mock.calls.length

        await expectLogic(logic, () => {
            logic.actions.setSceneState(456 as any, FORM_MODES.update)
        }).toMatchValues({
            experimentId: 456,
            formMode: FORM_MODES.update,
        })

        const afterFirstCall = mockModule.experimentLogic.build.mock.calls.length

        await expectLogic(logic, () => {
            logic.actions.setSceneState(456 as any, FORM_MODES.update)
        }).toMatchValues({
            experimentId: 456,
            formMode: FORM_MODES.update,
        })

        expect(mockModule.experimentLogic.build.mock.calls.length).toBe(afterFirstCall)
        expect(afterFirstCall).toBeGreaterThan(initialBuildCount)

        logic.unmount()
    })

    it('loads experiment data when scene state changes', async () => {
        const logic = experimentSceneLogic({ tabId, experimentId: 789 as any, formMode: FORM_MODES.update })
        logic.mount()

        mockModule.experimentLogic.__logic.actions.loadExperiment.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setSceneState(789 as any, FORM_MODES.update)
        })

        expect(mockModule.experimentLogic.__logic.actions.loadExperiment).toHaveBeenCalledTimes(1)

        logic.unmount()
    })

    it('unmounts old experiment logic before mounting new one', async () => {
        const logic = experimentSceneLogic({ tabId, experimentId: 123 as any, formMode: FORM_MODES.update })
        logic.mount()

        const firstUnmount = mockModule.experimentLogic.__logic.getLastUnmountFn()

        mockModule.experimentLogic.build.mockClear()
        mockModule.experimentLogic.__logic.mount.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setSceneState(456 as any, FORM_MODES.update)
        })

        // Old logic should be unmounted before new one is mounted
        expect(firstUnmount).toHaveBeenCalled()
        expect(mockModule.experimentLogic.build).toHaveBeenCalledTimes(1)
        expect(mockModule.experimentLogic.__logic.mount).toHaveBeenCalledTimes(1)

        logic.unmount()
    })

    // Note: cleanup on scene unmount is handled by the beforeUnmount listener
    // The "unmounts old experiment logic before mounting new one" test above
    // verifies the unmount function is properly called when remounting
})
