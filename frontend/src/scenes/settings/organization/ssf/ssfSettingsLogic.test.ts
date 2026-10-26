import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { SSFStreamApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    SSF_INCOMING_CONNECTION,
    SSF_INCOMING_STREAM,
    SSF_OUTGOING_CONNECTION,
    SSF_SETTINGS,
} from './ssfSettingsFixtures'
import { ssfSettingsLogic } from './ssfSettingsLogic'

describe('ssfSettingsLogic', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => jest.restoreAllMocks())

    it('submits preset event selections without sending legacy receiver configuration', async () => {
        const requests: unknown[] = []
        const selected = SSF_SETTINGS.event_type_options.slice(0, 2).map((option) => option.key)
        let configuration = { ...SSF_SETTINGS, event_types: selected.slice(0, 1) }
        useMocks({
            get: {
                '/api/organizations/:organization/ssf': () => [200, configuration],
                '/api/organizations/:organization/ssf/connections': [],
                '/api/organizations/:organization/ssf/streams': [],
            },
            patch: {
                '/api/organizations/:organization/ssf/configuration': async ({ request }) => {
                    requests.push(await request.json())
                    configuration = { ...SSF_SETTINGS, event_types: selected }
                    return [200, configuration]
                },
            },
        })
        const logic = ssfSettingsLogic({ organizationId: 'organization-one' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.ssf.eventTypes).toEqual(selected.slice(0, 1))
        logic.actions.setSsfValues({ eventTypes: selected })
        await expectLogic(logic, () => logic.actions.submitSsf())
            .toDispatchActions(['submitSsfSuccess'])
            .toFinishAllListeners()
        expect(requests).toEqual([{ event_types: selected }])
        expect(logic.values.ssf.eventTypes).toEqual(selected)
        expect(logic.values.isSsfSubmitting).toBe(false)
        logic.unmount()
    })

    it.each([true, false])(
        'saves enabled=%s independently of event-type edits and allows retry after failure',
        async (enabled) => {
            const successToast = jest.spyOn(lemonToast, 'success')
            const requests: unknown[] = []
            let configuration = { ...SSF_SETTINGS, enabled: !enabled }
            let fail = true
            useMocks({
                get: {
                    '/api/organizations/:organization/ssf': () => [200, configuration],
                    '/api/organizations/:organization/ssf/connections': [],
                    '/api/organizations/:organization/ssf/streams': [],
                },
                patch: {
                    '/api/organizations/:organization/ssf/configuration': async ({ request }) => {
                        requests.push(await request.json())
                        if (fail) {
                            fail = false
                            return [500, { detail: 'Could not save configuration.' }]
                        }
                        configuration = { ...configuration, enabled }
                        return [200, configuration]
                    },
                },
            })
            const logic = ssfSettingsLogic({ organizationId: 'organization-one' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const eventTypes = SSF_SETTINGS.event_type_options.slice(0, 1).map((option) => option.key)
            logic.actions.setSsfValue('eventTypes', eventTypes)
            await expectLogic(logic, () => logic.actions.setEnabled({ enabled }))
                .toDispatchActions(['setEnabledFailure'])
                .toFinishAllListeners()
            expect(successToast).not.toHaveBeenCalled()
            expect(logic.values.configuration?.enabled).toBe(!enabled)
            expect(logic.values.configurationLoading).toBe(false)
            expect(logic.values.ssf.eventTypes).toEqual(eventTypes)
            await expectLogic(logic, () => logic.actions.setEnabled({ enabled }))
                .toDispatchActions(['setEnabledSuccess'])
                .toFinishAllListeners()
            expect(successToast).toHaveBeenCalledTimes(1)
            expect(successToast).toHaveBeenCalledWith(enabled ? 'SSF enabled.' : 'SSF disabled.')
            expect(requests).toEqual([{ enabled }, { enabled }])
            expect(logic.values.configuration?.enabled).toBe(enabled)
            expect(logic.values.configurationLoading).toBe(false)
            expect(logic.values.ssf.eventTypes).toEqual(eventTypes)
            logic.unmount()
        }
    )

    it('keeps management credentials scoped to their connection and organization', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/ssf': SSF_SETTINGS,
                '/api/organizations/:organization/ssf/connections': [SSF_OUTGOING_CONNECTION],
                '/api/organizations/:organization/ssf/streams': [],
            },
            post: {
                '/api/organizations/:organization/ssf/connections/:connection/rotate_token': {
                    token: 'phssf_example_not_a_real_credential',
                },
            },
        })
        const first = ssfSettingsLogic({ organizationId: 'organization-one' })
        const second = ssfSettingsLogic({ organizationId: 'organization-two' })
        first.mount()
        second.mount()
        await expectLogic(first).toFinishAllListeners()
        await expectLogic(second).toFinishAllListeners()
        await expectLogic(first, () => first.actions.rotateToken({ id: SSF_OUTGOING_CONNECTION.id }))
            .toDispatchActions(['rotateTokenSuccess'])
            .toFinishAllListeners()
        expect(first.values.credential).toEqual({
            token: 'phssf_example_not_a_real_credential',
            connectionId: SSF_OUTGOING_CONNECTION.id,
        })
        expect(second.values.credential).toBeNull()
        first.actions.clearCredential()
        expect(first.values.credential).toBeNull()
        expect(first.values.credentialLoading).toBe(false)
        first.unmount()
        second.unmount()
    })

    it('creates multiple incoming streams on one connection without manually entered keys or stream IDs', async () => {
        const requests: unknown[] = []
        const streams: SSFStreamApi[] = []
        const updates: unknown[] = []
        useMocks({
            get: {
                '/api/organizations/:organization/ssf': SSF_SETTINGS,
                '/api/organizations/:organization/ssf/connections': [SSF_INCOMING_CONNECTION],
                '/api/organizations/:organization/ssf/streams': () => [200, streams],
            },
            post: {
                '/api/organizations/:organization/ssf/streams': async ({ request }) => {
                    requests.push(await request.json())
                    const stream = { ...SSF_INCOMING_STREAM, id: `example-stream-${requests.length}` }
                    streams.push(stream)
                    return [201, stream]
                },
            },
            patch: {
                '/api/organizations/:organization/ssf/streams/:stream': async ({ request }) => {
                    updates.push(await request.json())
                    return [200, streams[0]]
                },
            },
        })
        const logic = ssfSettingsLogic({ organizationId: 'organization-one' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        for (const description of ['Account events', 'Device events']) {
            logic.actions.openStream()
            logic.actions.setStreamValues({ connection: SSF_INCOMING_CONNECTION.id, description, eventTypes: [] })
            await expectLogic(logic, () => logic.actions.submitStream())
                .toDispatchActions(['submitStreamSuccess'])
                .toFinishAllListeners()
        }
        expect(requests).toEqual([
            { connection: SSF_INCOMING_CONNECTION.id, description: 'Account events' },
            { connection: SSF_INCOMING_CONNECTION.id, description: 'Device events' },
        ])
        expect(logic.values.streams).toHaveLength(2)
        logic.actions.openStream(streams[0])
        logic.actions.setStreamValue('description', 'Updated account events')
        await expectLogic(logic, () => logic.actions.submitStream())
            .toDispatchActions(['submitStreamSuccess'])
            .toFinishAllListeners()
        expect(updates).toEqual([{ description: 'Updated account events', events_requested: [] }])
        expect(logic.values.streams).toHaveLength(2)
        expect(logic.values.streamOpen).toBe(false)
        logic.unmount()
    })

    it('does not overwrite a saved transmitter API token when editing the connection name', async () => {
        const requests: unknown[] = []
        useMocks({
            get: {
                '/api/organizations/:organization/ssf': SSF_SETTINGS,
                '/api/organizations/:organization/ssf/connections': [SSF_INCOMING_CONNECTION],
                '/api/organizations/:organization/ssf/streams': [],
            },
            patch: {
                '/api/organizations/:organization/ssf/connections/:connection': async ({ request }) => {
                    requests.push(await request.json())
                    return [200, SSF_INCOMING_CONNECTION]
                },
            },
        })
        const logic = ssfSettingsLogic({ organizationId: 'organization-one' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openConnection(SSF_INCOMING_CONNECTION)
        expect(logic.values.connection.remote_token).toBe('')
        logic.actions.setConnectionValue('name', 'Renamed transmitter')
        await expectLogic(logic, () => logic.actions.submitConnection())
            .toDispatchActions(['submitConnectionSuccess'])
            .toFinishAllListeners()
        expect(requests).toEqual([{ name: 'Renamed transmitter' }])
        expect(logic.values.connectionOpen).toBe(false)
        logic.unmount()
    })

    it('refreshes pending verification until the incoming event is confirmed', async () => {
        let tick: (() => void) | undefined
        const interval = jest.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler) => {
            if (typeof handler === 'function') {
                tick = () => handler()
            }
            return 0
        })
        let reads = 0
        useMocks({
            get: {
                '/api/organizations/:organization/ssf': SSF_SETTINGS,
                '/api/organizations/:organization/ssf/connections': [SSF_INCOMING_CONNECTION],
                '/api/organizations/:organization/ssf/streams': () => {
                    reads++
                    return [
                        200,
                        [
                            {
                                ...SSF_INCOMING_STREAM,
                                verification_pending: reads === 1,
                                last_verified_at: reads === 1 ? null : '2026-10-23T12:00:00Z',
                            },
                        ],
                    ]
                },
            },
        })
        const logic = ssfSettingsLogic({ organizationId: 'organization-one' })
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.streams?.[0].verification_pending).toBe(true)
            await expectLogic(logic, () => tick?.())
                .toDispatchActions(['loadStreams'])
                .toFinishAllListeners()
            expect(logic.values.streams?.[0].last_verified_at).toBe('2026-10-23T12:00:00Z')
            expect(logic.values.streams?.[0].verification_pending).toBe(false)
            tick?.()
            expect(reads).toBe(2)
        } finally {
            logic.unmount()
            interval.mockRestore()
        }
    })
})
