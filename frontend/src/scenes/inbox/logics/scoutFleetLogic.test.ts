import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigUpdate,
    signalsScoutMetadataGet,
} from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigUpdate: jest.fn(),
    signalsScoutMetadataGet: jest.fn(),
    signalsScoutRunsFindingsSummary: jest.fn(),
}))

const mockSignalsScoutConfigList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockSignalsScoutConfigUpdate = signalsScoutConfigUpdate as jest.MockedFunction<typeof signalsScoutConfigUpdate>
const mockSignalsScoutMetadataGet = signalsScoutMetadataGet as jest.MockedFunction<typeof signalsScoutMetadataGet>

const BASE_CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-errors',
    description: 'Finds error trends.',
    scout_origin: 'canonical',
    enabled: true,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    last_run_at: null,
    created_at: '2026-07-22T00:00:00Z',
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolvePromise!: (value: T) => void
    let rejectPromise!: (error: Error) => void
    const promise = new Promise<T>((resolve, reject) => {
        resolvePromise = resolve
        rejectPromise = reject
    })
    return { promise, resolve: resolvePromise, reject: rejectPromise }
}

describe('scoutFleetLogic', () => {
    let logic: ReturnType<typeof scoutFleetLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockSignalsScoutConfigList.mockReset().mockResolvedValue([])
        mockSignalsScoutConfigUpdate.mockReset()
        mockSignalsScoutMetadataGet.mockReset().mockResolvedValue({
            enrolled: true,
            banner_message: null,
            limits: {
                max_runs_per_tick: 1,
                max_runs_per_day: null,
                runs_today: 0,
                runs_remaining_today: null,
            },
        })

        logic = scoutFleetLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadScoutConfigsSuccess([BASE_CONFIG])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('queues updates for a scout while its previous update is in flight', async () => {
        const firstRequest = deferred<SignalScoutConfigApi>()
        const queuedUpdates = {
            run_interval_minutes: 60,
            output_destinations: {
                slack: { integration_id: 42, channel: 'CSCOUTS|#scout-findings' },
            },
        }
        const finalConfig: SignalScoutConfigApi = {
            ...BASE_CONFIG,
            enabled: false,
            ...queuedUpdates,
        }
        mockSignalsScoutConfigUpdate.mockReturnValueOnce(firstRequest.promise).mockResolvedValueOnce(finalConfig)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { enabled: false })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { run_interval_minutes: 60 })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { output_destinations: queuedUpdates.output_destinations })

        expect(mockSignalsScoutConfigUpdate).toHaveBeenCalledTimes(1)
        expect(logic.values.scoutConfigs?.[0]).toMatchObject({ enabled: false, ...queuedUpdates })

        firstRequest.resolve({ ...BASE_CONFIG, enabled: false })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(1, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            enabled: false,
        })
        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(
            2,
            String(MOCK_TEAM_ID),
            BASE_CONFIG.id,
            queuedUpdates
        )
        expect(logic.values.scoutConfigs?.[0]).toEqual(finalConfig)
        expect(logic.values.updatingScoutIds).toEqual([])
    })

    it('keeps configs unresolved until the current team is available', async () => {
        logic.unmount()
        teamLogic.actions.loadCurrentTeamSuccess(null)
        mockSignalsScoutConfigList.mockClear()
        logic = scoutFleetLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigList).not.toHaveBeenCalled()
        expect(logic.values.scoutConfigs).toBeNull()
    })

    it('sends newer queued updates after an earlier request fails', async () => {
        const firstRequest = deferred<SignalScoutConfigApi>()
        const failingRequest = deferred<SignalScoutConfigApi>()
        const outputDestinations = {
            slack: { integration_id: 42, channel: 'CSCOUTS|#scout-findings' },
        }
        const finalConfig: SignalScoutConfigApi = {
            ...BASE_CONFIG,
            enabled: false,
            output_destinations: outputDestinations,
        }
        mockSignalsScoutConfigUpdate
            .mockReturnValueOnce(firstRequest.promise)
            .mockReturnValueOnce(failingRequest.promise)
            .mockResolvedValueOnce(finalConfig)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { enabled: false })
        logic.actions.updateScoutConfig(BASE_CONFIG.id, { run_interval_minutes: 60 })

        firstRequest.resolve({ ...BASE_CONFIG, enabled: false })
        await expectLogic(logic).toDispatchActions(['patchScoutConfigLocally'])
        expect(mockSignalsScoutConfigUpdate).toHaveBeenCalledTimes(2)

        logic.actions.updateScoutConfig(BASE_CONFIG.id, { output_destinations: outputDestinations })
        failingRequest.reject(new Error('request failed'))
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(2, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            run_interval_minutes: 60,
        })
        expect(mockSignalsScoutConfigUpdate).toHaveBeenNthCalledWith(3, String(MOCK_TEAM_ID), BASE_CONFIG.id, {
            output_destinations: outputDestinations,
        })
        expect(logic.values.scoutConfigs?.[0]).toEqual(finalConfig)
        expect(logic.values.updatingScoutIds).toEqual([])
    })
})
