import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { FORM_MODES } from './experimentLogic'
import { DEFAULT_EXPERIMENT_TAB, experimentSceneLogic } from './experimentSceneLogic'

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
                refreshStaleResultsOnReentry: jest.Mock
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
            refreshStaleResultsOnReentry: jest.fn(),
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

const mockModule = require('./experimentLogic') as ExperimentLogicMock

describe('experimentSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockModule.experimentLogic.__logic.actions.loadExperiment.mockClear()
        mockModule.experimentLogic.__logic.actions.loadExposures.mockClear()
    })

    it('mounts experiment logic on scene state change', async () => {
        const logic = experimentSceneLogic({ experimentId: 'new', formMode: FORM_MODES.create })
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
        const logic = experimentSceneLogic({ experimentId: 456 as any, formMode: FORM_MODES.update })
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

    it('loads experiment data when scene state changes', async () => {
        const logic = experimentSceneLogic({ experimentId: 789 as any, formMode: FORM_MODES.update })
        logic.mount()

        mockModule.experimentLogic.__logic.actions.loadExperiment.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setSceneState(789 as any, FORM_MODES.update)
        })

        expect(mockModule.experimentLogic.__logic.actions.loadExperiment).toHaveBeenCalledTimes(1)

        logic.unmount()
    })

    it('reports a tab view only when the active tab actually changes', async () => {
        // LemonTabs fires onChange on every tab click, including clicks on the already-active
        // tab, so a same-tab dispatch must not count as another view.
        const capture = posthog.capture as jest.Mock
        router.actions.push(urls.experiment(123))
        const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
        logic.mount()
        // Mounting replays `urlToAction` for the current URL, which reports the landing tab —
        // not this test's subject.
        capture.mockClear()

        logic.actions.setActiveTabKey('recordings')
        logic.actions.setActiveTabKey('recordings')
        logic.actions.setActiveTabKey('metrics')
        await expectLogic(logic).toFinishAllListeners()

        const tabViews = capture.mock.calls.filter(([event]) => event === 'experiment tab viewed')
        expect(tabViews.map(([, properties]) => (properties as any)?.tab)).toEqual(['recordings', 'metrics'])

        logic.unmount()
    })

    describe('tab query param sync', () => {
        it('hydrates the tab from ?tab on load and keeps the param in the URL', async () => {
            router.actions.push(urls.experiment(123), { tab: 'variants' })
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic).toMatchValues({ activeTabKey: 'variants' })
            expect(router.values.searchParams['tab']).toEqual('variants')

            logic.unmount()
        })

        it('falls back to the default tab for an unknown ?tab value', async () => {
            router.actions.push(urls.experiment(123), { tab: 'bogus' })
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic).toMatchValues({ activeTabKey: DEFAULT_EXPERIMENT_TAB })

            logic.unmount()
        })

        it('opens the history tab for an ?activity deep link and keeps the param in the URL', async () => {
            router.actions.push(urls.experiment(123), { activity: 'some-uuid' })
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic).toMatchValues({ activeTabKey: 'history' })
            expect(router.values.searchParams['activity']).toEqual('some-uuid')

            logic.unmount()
        })

        it('writes the tab to the URL with replace and clears it for the default tab', async () => {
            router.actions.push(urls.experiment(123))
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic, () => logic.actions.setActiveTabKey('code'))
            expect(router.values.searchParams['tab']).toEqual('code')
            expect(router.values.lastMethod).toEqual('REPLACE')

            await expectLogic(logic, () => logic.actions.setActiveTabKey(DEFAULT_EXPERIMENT_TAB))
            expect(router.values.searchParams['tab']).toBeUndefined()

            logic.unmount()
        })

        it('drops the activity param when switching away from the history tab', async () => {
            router.actions.push(urls.experiment(123), { activity: 'some-uuid' })
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic).toMatchValues({ activeTabKey: 'history' })

            await expectLogic(logic, () => logic.actions.setActiveTabKey('variants')).toMatchValues({
                activeTabKey: 'variants',
            })
            expect(router.values.searchParams['activity']).toBeUndefined()
            expect(router.values.searchParams['tab']).toEqual('variants')

            logic.unmount()
        })

        it('resets to the default tab when navigating to another experiment', async () => {
            router.actions.push(urls.experiment(123), { tab: 'variants' })
            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()

            await expectLogic(logic).toMatchValues({ activeTabKey: 'variants' })

            await expectLogic(logic, () => router.actions.push(urls.experiment(456))).toMatchValues({
                activeTabKey: DEFAULT_EXPERIMENT_TAB,
            })

            logic.unmount()
        })

        it.each([
            ['a ?tab deep link', { tab: 'code' }, 'code'],
            ['no tab params', {}, 'metrics'],
        ])('reports exactly one tab view when landing with %s', async (_label, searchParams, expectedTab) => {
            // A landing must report once whether the listener fires (tab differs from the
            // default) or the explicit landing report does (tab already active).
            const capture = posthog.capture as jest.Mock
            router.actions.push(urls.experiment(123), searchParams)
            capture.mockClear()

            const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const tabViews = capture.mock.calls.filter(([event]) => event === 'experiment tab viewed')
            expect(tabViews.map(([, properties]) => (properties as any)?.tab)).toEqual([expectedTab])

            logic.unmount()
        })
    })
})
