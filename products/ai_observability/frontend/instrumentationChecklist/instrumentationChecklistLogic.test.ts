import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import {
    aiObservabilityInstrumentationChecklistDismissCreate,
    aiObservabilityInstrumentationChecklistRestoreCreate,
    aiObservabilityInstrumentationChecklistRetrieve,
} from '../generated/api'
import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckStatusEnumApi,
    InstrumentationChecklistApi,
} from '../generated/api.schemas'
import {
    InstrumentationChecklistCardState,
    clearCachedChecklistVerdict,
    instrumentationChecklistLogic,
} from './instrumentationChecklistLogic'

jest.mock('../generated/api', () => ({
    aiObservabilityInstrumentationChecklistRetrieve: jest.fn(),
    aiObservabilityInstrumentationChecklistDismissCreate: jest.fn(),
    aiObservabilityInstrumentationChecklistRestoreCreate: jest.fn(),
}))

const mockRetrieve = aiObservabilityInstrumentationChecklistRetrieve as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRetrieve
>
const mockDismiss = aiObservabilityInstrumentationChecklistDismissCreate as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistDismissCreate
>
const mockRestore = aiObservabilityInstrumentationChecklistRestoreCreate as jest.MockedFunction<
    typeof aiObservabilityInstrumentationChecklistRestoreCreate
>

const CHECK_KEYS = [
    AIObservabilityInstrumentationCheckEnumApi.Sessions,
    AIObservabilityInstrumentationCheckEnumApi.ToolCalls,
    AIObservabilityInstrumentationCheckEnumApi.UserIdentity,
    AIObservabilityInstrumentationCheckEnumApi.TraceStructure,
]

function buildChecklist(...statuses: InstrumentationCheckStatusEnumApi[]): InstrumentationChecklistApi {
    return {
        window_days: 30,
        checks: statuses.map((status, index) => ({
            key: CHECK_KEYS[index],
            status,
            title: 'Sessions',
            detail: 'A sentence about the counts.',
            docs_url: 'https://posthog.com/docs/ai-observability/installation',
            stats: { generations: 100 },
        })),
    }
}

const ALL_OK = buildChecklist(
    InstrumentationCheckStatusEnumApi.Ok,
    InstrumentationCheckStatusEnumApi.Ok,
    InstrumentationCheckStatusEnumApi.Ok,
    InstrumentationCheckStatusEnumApi.Ok
)

describe('instrumentationChecklistLogic', () => {
    let logic: ReturnType<typeof instrumentationChecklistLogic.build>

    function setFlag(enabled: boolean): void {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_INSTRUMENTATION_CHECKLIST]: enabled,
        })
    }

    beforeEach(() => {
        jest.clearAllMocks()
        // The verdict cache is module state, so it outlives a logic unmount by design and would
        // otherwise carry one test's checklist into the next.
        clearCachedChecklistVerdict()
        mockRetrieve.mockResolvedValue(ALL_OK)
        initKeaTests()
        featureFlagLogic.mount()
        setFlag(true)
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
    })

    it('reuses a fresh verdict instead of refetching on every remount', async () => {
        // The trace view mounts this logic once per trace opened, and the read behind it is an
        // uncached 30 day aggregate, so a remount has to reuse the verdict rather than refire it.
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        logic.unmount()

        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.checklistCardState).toBe('passing')
    })

    it('loads the checklist on mount and exposes the graded checks', async () => {
        const checklist = buildChecklist(
            InstrumentationCheckStatusEnumApi.Warning,
            InstrumentationCheckStatusEnumApi.Ok,
            InstrumentationCheckStatusEnumApi.Pending,
            InstrumentationCheckStatusEnumApi.Dismissed
        )
        mockRetrieve.mockResolvedValue(checklist)
        logic = instrumentationChecklistLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.checks).toEqual(checklist.checks)
        expect(logic.values.windowDays).toBe(30)
    })

    it('makes no request while the feature flag is off', async () => {
        setFlag(false)
        logic = instrumentationChecklistLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(mockRetrieve).not.toHaveBeenCalled()
        expect(logic.values.checklist).toBeNull()
        expect(logic.values.checklistCardState).toBe('hidden')
    })

    it('loads once the feature flag arrives after mount', async () => {
        setFlag(false)
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        setFlag(true)

        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.checklistCardState).toBe('passing')
    })

    it('loads when the feature flag arrives in the same tick as mount', async () => {
        setFlag(false)
        logic = instrumentationChecklistLogic()
        logic.mount()
        // No awaiting: this is the cold-page ordering, where flags land while a mount-time load
        // would still be in flight. A load started before the flag resolves returns null and blocks
        // the retry, so the card would sit hidden behind a skeleton that never resolves.
        setFlag(true)

        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.checklistCardState).toBe('passing')
    })

    it('leaves every consumer on generic copy when the request fails, with nothing surfaced', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        mockRetrieve.mockRejectedValue({ status: 500, detail: 'Something broke' })
        logic = instrumentationChecklistLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistFailure'])
        expect(logic.values.checklist).toBeNull()
        expect(logic.values.checks).toEqual([])
        expect(logic.values.checklistCardState).toBe('hidden')
        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)).toBeNull()
        expect(logic.values.refreshFailed).toBe(false)
        expect(toastError).not.toHaveBeenCalled()
    })

    it('flags a failed refresh, and clears the flag once a later load answers', async () => {
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(logic.values.refreshFailed).toBe(false)

        mockRetrieve.mockRejectedValue({ status: 500 })
        logic.actions.loadInstrumentationChecklist()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistFailure'])
        expect(logic.values.refreshFailed).toBe(true)
        expect(logic.values.checklistCardState).toBe('passing')

        mockRetrieve.mockResolvedValue(ALL_OK)
        logic.actions.loadInstrumentationChecklist()
        expect(logic.values.refreshFailed).toBe(false)
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(logic.values.refreshFailed).toBe(false)
    })

    const cardStateCases: [string, InstrumentationCheckStatusEnumApi[], InstrumentationChecklistCardState][] = [
        [
            'a warning is present',
            [
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Dismissed,
            ],
            'warnings',
        ],
        [
            'everything is ok or dismissed',
            [
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Dismissed,
            ],
            'passing',
        ],
        [
            'everything is dismissed',
            [
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Dismissed,
            ],
            'passing',
        ],
        [
            'every check is below its volume floor',
            [
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
            ],
            'collecting',
        ],
        [
            'every check that was not dismissed is below its volume floor',
            [
                InstrumentationCheckStatusEnumApi.Dismissed,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
            ],
            'collecting',
        ],
        [
            'only some checks are below their volume floor',
            [
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Pending,
            ],
            'passing',
        ],
    ]

    it.each(cardStateCases)('reports card state %s', async (_, statuses, expected) => {
        mockRetrieve.mockResolvedValue(buildChecklist(...statuses))
        logic = instrumentationChecklistLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(logic.values.checklistCardState).toBe(expected)
    })

    // A stopped rollout has to take the card and the empty-state overrides with it, including in
    // tabs that are already open and on the load where localStorage replays the old flag set.
    it('takes a loaded checklist back off screen when the flag goes off', async () => {
        mockRetrieve.mockResolvedValue(
            buildChecklist(
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok
            )
        )
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        expect(logic.values.checklistCardState).toBe('warnings')

        setFlag(false)

        expect(logic.values.checklistCardState).toBe('hidden')
        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)).toBeNull()
    })

    it('only offers a check to an empty state when that check is warning', async () => {
        mockRetrieve.mockResolvedValue(
            buildChecklist(
                InstrumentationCheckStatusEnumApi.Warning,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Pending,
                InstrumentationCheckStatusEnumApi.Dismissed
            )
        )
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)?.key).toBe('sessions')
        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.ToolCalls)).toBeNull()
        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.UserIdentity)).toBeNull()
        expect(logic.values.warningForCheck(AIObservabilityInstrumentationCheckEnumApi.TraceStructure)).toBeNull()
    })

    const writeCases: [
        string,
        () => typeof mockDismiss,
        (check: AIObservabilityInstrumentationCheckEnumApi) => void,
        InstrumentationCheckStatusEnumApi,
    ][] = [
        [
            'dismissCheck',
            () => mockDismiss,
            (check) => logic.actions.dismissCheck(check),
            InstrumentationCheckStatusEnumApi.Dismissed,
        ],
        [
            'restoreCheck',
            () => mockRestore,
            (check) => logic.actions.restoreCheck(check),
            InstrumentationCheckStatusEnumApi.Warning,
        ],
    ]

    it.each(writeCases)(
        'applies the checklist %s returns without refetching',
        async (_, getMock, write, resultingStatus) => {
            const recomputed = buildChecklist(
                resultingStatus,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok,
                InstrumentationCheckStatusEnumApi.Ok
            )
            getMock().mockResolvedValue(recomputed)
            logic = instrumentationChecklistLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

            await expectLogic(logic, () => {
                write(AIObservabilityInstrumentationCheckEnumApi.Sessions)
            }).toFinishAllListeners()

            expect(getMock()).toHaveBeenCalledWith(expect.any(String), { check: 'sessions' })
            expect(logic.values.checks[0].status).toBe(resultingStatus)
            expect(logic.values.pendingCheckKey).toBeNull()
            expect(mockRetrieve).toHaveBeenCalledTimes(1)
        }
    )

    it('surfaces a failed write rather than leaving the click looking ignored', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        mockDismiss.mockRejectedValue({ status: 500 })
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])
        const statusBeforeWrite = logic.values.checks[0].status

        await expectLogic(logic, () => {
            logic.actions.dismissCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)
        }).toFinishAllListeners()

        expect(toastError).toHaveBeenCalledTimes(1)
        expect(logic.values.checks[0].status).toBe(statusBeforeWrite)
        expect(logic.values.pendingCheckKey).toBeNull()
        expect(logic.values.checklistBusy).toBe(false)
    })

    it('ignores a repeat dismissal of the same check while the first is still in flight', async () => {
        let resolveDismiss: (checklist: InstrumentationChecklistApi) => void = () => {}
        mockDismiss.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveDismiss = resolve
                })
        )
        logic = instrumentationChecklistLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstrumentationChecklistSuccess'])

        logic.actions.dismissCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)
        logic.actions.dismissCheck(AIObservabilityInstrumentationCheckEnumApi.Sessions)
        expect(mockDismiss).toHaveBeenCalledTimes(1)
        expect(logic.values.pendingCheckKey).toBe('sessions')
        expect(logic.values.checklistBusy).toBe(true)

        resolveDismiss(ALL_OK)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingCheckKey).toBeNull()
        expect(logic.values.checklistBusy).toBe(false)
    })
})
