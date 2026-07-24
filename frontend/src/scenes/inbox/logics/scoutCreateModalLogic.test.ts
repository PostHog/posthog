import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { signalsScoutCreate } from 'products/signals/frontend/generated/api'
import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { SCOUT_DAILY_AT_SCHEDULE_MODE } from '../utils/scoutRunsWindow'
import { ScoutCreateModalLogicProps, scoutCreateModalLogic } from './scoutCreateModalLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutCreate: jest.fn(),
}))

const mockSignalsScoutCreate = signalsScoutCreate as jest.MockedFunction<typeof signalsScoutCreate>

const CREATED_SCOUT: SignalScoutCreateResponseApi = {
    created: true,
    skill: {
        id: 'skill-1',
        name: 'signals-scout-checkout-failures',
        description: 'Investigates recurring checkout failures.',
        version: 1,
        allowed_tools: ['edit_report', 'emit_report'],
    },
    config: {
        id: 'config-1',
        skill_name: 'signals-scout-checkout-failures',
        description: 'Investigates recurring checkout failures.',
        scout_origin: 'custom',
        enabled: false,
        emit: false,
        run_interval_minutes: 60,
        run_cron_schedule: null,
        output_destinations: {},
        last_run_at: null,
        created_at: '2026-07-24T00:00:00Z',
    },
}

describe('scoutCreateModalLogic', () => {
    let logic: ReturnType<typeof scoutCreateModalLogic.build>
    let onClose: jest.MockedFunction<() => void>
    let onCreated: jest.MockedFunction<NonNullable<ScoutCreateModalLogicProps['onCreated']>>

    beforeEach(() => {
        initKeaTests()
        mockSignalsScoutCreate.mockReset()
        onClose = jest.fn()
        onCreated = jest.fn()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('merges trigger defaults and submits them to the atomic create endpoint', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'prefilled-scout',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
                config: {
                    enabled: false,
                    emit: false,
                    run_interval_minutes: 60,
                    output_destinations: {
                        slack: {
                            integration_id: 42,
                            channel: 'C123|#ai-observability',
                        },
                    },
                },
            },
            onClose,
            onCreated,
        })
        logic.mount()

        expect(logic.values.scoutCreateForm).toEqual({
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
            dailyTime: '09:00',
            config: {
                enabled: false,
                emit: false,
                run_interval_minutes: 60,
                run_cron_schedule: null,
                output_destinations: {
                    slack: {
                        integration_id: 42,
                        channel: 'C123|#ai-observability',
                    },
                },
            },
        })

        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
            config: {
                enabled: false,
                emit: false,
                run_interval_minutes: 60,
                run_cron_schedule: null,
                output_destinations: {
                    slack: {
                        integration_id: 42,
                        channel: 'C123|#ai-observability',
                    },
                },
            },
        })
        expect(onCreated).toHaveBeenCalledWith(CREATED_SCOUT)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('submits a daily run time as a project-timezone cron schedule', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'daily-scout',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateScheduleMode(SCOUT_DAILY_AT_SCHEDULE_MODE)
        logic.actions.setScoutCreateDailyTime('14:45')

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({
                dailyTime: '14:45',
                config: {
                    enabled: true,
                    emit: true,
                    run_interval_minutes: 1440,
                    run_cron_schedule: '45 14 * * *',
                },
            }),
        })
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).toHaveBeenCalledWith(
            String(MOCK_TEAM_ID),
            expect.objectContaining({
                config: {
                    enabled: true,
                    emit: true,
                    run_interval_minutes: 1440,
                    run_cron_schedule: '45 14 * * *',
                },
            })
        )
    })

    it('does not submit a daily schedule without a run time', async () => {
        mockSignalsScoutCreate.mockResolvedValue(CREATED_SCOUT)
        logic = scoutCreateModalLogic({
            logicKey: 'daily-scout-without-time',
            initialValues: {
                name: 'signals-scout-checkout-failures',
                description: 'Investigates recurring checkout failures.',
                body: 'Inspect checkout failure signals and report meaningful regressions.',
            },
            onClose,
            onCreated,
        })
        logic.mount()

        logic.actions.setScoutCreateScheduleMode(SCOUT_DAILY_AT_SCHEDULE_MODE)
        logic.actions.setScoutCreateDailyTime('')

        await expectLogic(logic).toMatchValues({
            scoutCreateForm: expect.objectContaining({ dailyTime: '' }),
            scoutCreateFormValidationErrors: expect.objectContaining({ dailyTime: 'Run time is required' }),
        })
        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(mockSignalsScoutCreate).not.toHaveBeenCalled()
        expect(onCreated).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })

    it('keeps the form open and surfaces a conflicting scout name', async () => {
        const initialValues = {
            name: 'signals-scout-checkout-failures',
            description: 'Investigates recurring checkout failures.',
            body: 'Inspect checkout failure signals and report meaningful regressions.',
        }
        mockSignalsScoutCreate.mockRejectedValue(
            new ApiError('Conflict', 409, undefined, {
                detail: 'A scout with this name already exists with different instructions.',
                attr: 'name',
            })
        )
        logic = scoutCreateModalLogic({
            logicKey: 'conflicting-scout',
            initialValues,
            onClose,
            onCreated,
        })
        logic.mount()

        await expectLogic(logic, () => logic.actions.submitScoutCreateForm()).toFinishAllListeners()

        expect(logic.values.scoutCreateFormManualErrors).toEqual({
            name: 'A scout with this name already exists with different instructions.',
        })
        expect(logic.values.scoutCreateForm).toMatchObject(initialValues)
        expect(onCreated).not.toHaveBeenCalled()
        expect(onClose).not.toHaveBeenCalled()
    })
})
