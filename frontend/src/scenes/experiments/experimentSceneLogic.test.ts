import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { FORM_MODES } from './experimentLogic'
import { DEFAULT_EXPERIMENT_TAB, experimentSceneLogic, getAvailableExperimentTabs } from './experimentSceneLogic'

const LEGACY_EXPERIMENT = {
    id: 123,
    metrics: [{ kind: NodeKind.ExperimentTrendsQuery }],
} as unknown as Experiment
const DRAFT_EXPERIMENT = { id: 123 } as Experiment
const LAUNCHED_EXPERIMENT = { id: 123, start_date: '2020-01-01T00:00:00Z' } as Experiment

type ExperimentLogicMock = {
    experimentLogic: {
        build: jest.Mock<any, any>
        // Presents a loaded experiment through the same selector the scene proxies. Undefined (the
        // default) leaves the scene reading the NEW_EXPERIMENT placeholder, i.e. "still loading".
        __setExperiment: (experiment: Partial<Experiment> | undefined) => void
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
    const experimentHolder: { current: any } = { current: undefined }
    const logicInstance = {
        mount: jest.fn(() => jest.fn()),
        actions: {
            setEditExperiment: jest.fn(),
            resetExperiment: jest.fn(),
            loadExperiment: jest.fn(),
            loadExposures: jest.fn(),
            refreshStaleResultsOnReentry: jest.fn(),
        },
        selectors: {
            experiment: () => experimentHolder.current,
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
            __setExperiment: (experiment: any) => {
                experimentHolder.current = experiment
            },
        },
        NEW_EXPERIMENT: { id: 'new' },
    }
})

const mockModule = require('./experimentLogic') as ExperimentLogicMock

describe('experimentSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockModule.experimentLogic.__setExperiment(undefined)
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

    describe('getAvailableExperimentTabs', () => {
        it('reduces legacy experiments to metrics and variants', () => {
            expect(getAvailableExperimentTabs(LEGACY_EXPERIMENT, {})).toEqual(['metrics', 'variants'])
        })

        it.each([
            ['launched experiments', LAUNCHED_EXPERIMENT, true],
            ['draft experiments', DRAFT_EXPERIMENT, false],
        ])('offers the code tab only for %s', (_label, experiment, expected) => {
            expect(getAvailableExperimentTabs(experiment, {}).includes('code')).toBe(expected)
        })

        it('offers the feedback tab only when a feature flag is linked', () => {
            expect(getAvailableExperimentTabs(DRAFT_EXPERIMENT, {}).includes('feedback')).toBe(false)
            const withFlag = { ...DRAFT_EXPERIMENT, feature_flag: { id: 1 } } as Experiment
            expect(getAvailableExperimentTabs(withFlag, {}).includes('feedback')).toBe(true)
        })

        it('offers the recordings tab only when the feature flag is enabled', () => {
            expect(getAvailableExperimentTabs(DRAFT_EXPERIMENT, {}).includes('recordings')).toBe(false)
            expect(
                getAvailableExperimentTabs(DRAFT_EXPERIMENT, {
                    [FEATURE_FLAGS.EXPERIMENT_RECORDINGS_TAB]: true,
                }).includes('recordings')
            ).toBe(true)
        })
    })

    it('clamps the active tab to the default once the experiment loads without it', async () => {
        // The deep-link path: ?tab=code resolves from the URL before the experiment loads, so the
        // scene holds 'code' provisionally. Once it loads as a draft (no code tab), scene state —
        // not just the rendered tab — must fall back to metrics, or the URL and the
        // `experiment tab viewed` event keep naming a tab the user never sees.
        router.actions.push(urls.experiment(123), { tab: 'code' })
        const logic = experimentSceneLogic({ experimentId: 123 as any, formMode: FORM_MODES.update })
        logic.mount()
        await expectLogic(logic).toMatchValues({ activeTabKey: 'code' })

        await expectLogic(logic, () => {
            // Simulate the experiment finishing loading as a draft; the ref update re-derives its
            // available tabs, standing in for the loadExperimentSuccess that swaps in real data.
            mockModule.experimentLogic.__setExperiment(DRAFT_EXPERIMENT)
            logic.actions.setExperimentLogicRef(mockModule.experimentLogic.__logic as any, jest.fn(), {
                experimentId: 123,
                formMode: FORM_MODES.update,
            } as any)
        }).toMatchValues({ activeTabKey: DEFAULT_EXPERIMENT_TAB })
        expect(router.values.searchParams['tab']).toBeUndefined()

        logic.unmount()
    })
})
