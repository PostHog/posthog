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
        }
    }
}

jest.mock('./experimentLogic', () => {
    const logicInstance = {
        mount: jest.fn(() => jest.fn()),
        actions: {
            setEditExperiment: jest.fn(),
            resetExperiment: jest.fn(),
            loadExperiment: jest.fn(),
            loadExposures: jest.fn(),
        },
        props: {},
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

        await expectLogic(logic, () => logic.actions.setSceneState(123 as any, FORM_MODES.update)).toMatchValues({
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

        await expectLogic(logic, () => logic.actions.setSceneState(456 as any, FORM_MODES.update)).toMatchValues({
            experimentId: 456,
            formMode: FORM_MODES.update,
        })

        const afterFirstCall = mockModule.experimentLogic.build.mock.calls.length

        await expectLogic(logic, () => logic.actions.setSceneState(456 as any, FORM_MODES.update)).toMatchValues({
            experimentId: 456,
            formMode: FORM_MODES.update,
        })

        expect(mockModule.experimentLogic.build.mock.calls.length).toBe(afterFirstCall)
        expect(afterFirstCall).toBeGreaterThan(initialBuildCount)

        logic.unmount()
    })

    it('delegates loading through the mounted experiment logic', async () => {
        const logic = experimentSceneLogic({ tabId, experimentId: 789 as any, formMode: FORM_MODES.update })
        logic.mount()

        mockModule.experimentLogic.__logic.actions.loadExperiment.mockClear()
        mockModule.experimentLogic.__logic.actions.loadExposures.mockClear()

        await expectLogic(logic, () => {
            logic.actions.loadExperimentData()
        })

        expect(mockModule.experimentLogic.__logic.actions.loadExperiment).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => {
            logic.actions.loadExposuresData(true)
        })

        expect(mockModule.experimentLogic.__logic.actions.loadExposures).toHaveBeenCalledWith(true)

        logic.unmount()
    })
})
