import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { customerEmailConfigLogic } from './customerEmailConfigLogic'
import type { CustomerEmailChannel } from './customerEmailConfigLogic'

describe('customerEmailConfigLogic', () => {
    let logic: ReturnType<typeof customerEmailConfigLogic.build>
    let getSpy: jest.SpyInstance
    let createSpy: jest.SpyInstance

    const channel: CustomerEmailChannel = {
        id: 'channel-1',
        from_email: 'csm@example.com',
        forwarding_address: 'team-token@inbound.example.com',
        connection_status: 'pending_confirmation',
        setup_expires_at: '2026-08-13T12:00:00Z',
        confirmation_available: false,
    }

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        userLogic.actions.loadUserSuccess({
            id: 7,
            email: 'csm@example.com',
            first_name: 'Casey',
            last_name: 'Manager',
        } as UserType)
        getSpy = jest.spyOn(api, 'get').mockResolvedValue({ configs: [] })
        createSpy = jest.spyOn(api, 'create')
        logic = customerEmailConfigLogic()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('loads only customer communication channels', async () => {
        getSpy.mockResolvedValue({ configs: [channel] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(getSpy).toHaveBeenCalledWith('api/conversations/v1/email/status?kind=customer_communication')
        expect(logic.values.channels).toEqual([channel])
        expect(logic.values.channelsLoading).toBe(false)
    })

    it('opens an authenticated confirmation without activating the channel', async () => {
        const replace = jest.fn()
        jest.spyOn(window, 'open').mockReturnValue({
            opener: window,
            location: { replace },
            close: jest.fn(),
        } as unknown as Window)
        getSpy.mockResolvedValue({
            configs: [{ ...channel, confirmation_available: true }],
        })
        createSpy.mockResolvedValue({
            ok: true,
            confirmation_url: 'https://mail-settings.google.com/mail/vf-confirmation',
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openGmailConfirmation(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith('api/conversations/v1/email/confirm-forwarding', {
            config_id: channel.id,
        })
        expect(window.open).toHaveBeenCalledWith('about:blank', '_blank')
        expect(replace).toHaveBeenCalledWith('https://mail-settings.google.com/mail/vf-confirmation')
        expect(logic.values.channels[0]).toEqual({ ...channel, confirmation_available: true })
        expect(logic.values.openingConfirmationChannelId).toBeNull()
    })

    it('sends a forwarding challenge and refreshes until the channel is active', async () => {
        jest.useFakeTimers()
        getSpy
            .mockResolvedValueOnce({ configs: [channel] })
            .mockResolvedValueOnce({ configs: [channel] })
            .mockResolvedValueOnce({
                configs: [
                    {
                        ...channel,
                        connection_status: 'active',
                        setup_expires_at: null,
                        confirmation_available: false,
                    },
                ],
            })
        createSpy.mockResolvedValue({ ok: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.verifyForwarding(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith('api/conversations/v1/email/verify-forwarding', {
            config_id: channel.id,
        })
        expect(logic.values.verifyingChannelId).toBeNull()
        expect(logic.values.verificationAwaitingChannelIds).toEqual([channel.id])
        expect(logic.values.channels[0].connection_status).toBe('pending_confirmation')
        expect(getSpy).toHaveBeenCalledTimes(2)

        await jest.advanceTimersByTimeAsync(3_000)
        await expectLogic(logic).toFinishAllListeners()

        expect(getSpy).toHaveBeenLastCalledWith('api/conversations/v1/email/status?kind=customer_communication')
        expect(getSpy).toHaveBeenCalledTimes(3)
        expect(logic.values.channels[0].connection_status).toBe('active')
        expect(logic.values.verificationAwaitingChannelIds).toEqual([])
    })

    it('does not overlap status refreshes', async () => {
        let runPoll = (): void => {}
        jest.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler): number => {
            if (typeof handler === 'function') {
                runPoll = () => handler()
            }
            return 1
        })
        getSpy.mockResolvedValue({ configs: [channel] })
        createSpy.mockResolvedValue({ ok: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.verifyForwarding(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        const completedRequestCount = getSpy.mock.calls.length
        let resolveRefresh!: (value: { configs: CustomerEmailChannel[] }) => void
        getSpy.mockReturnValueOnce(
            new Promise<{ configs: CustomerEmailChannel[] }>((resolve) => {
                resolveRefresh = resolve
            })
        )
        logic.actions.loadChannels(false)

        expect(logic.values.channelsLoading).toBe(true)
        runPoll()
        expect(getSpy).toHaveBeenCalledTimes(completedRequestCount + 1)

        resolveRefresh({ configs: [channel] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.channelsLoading).toBe(false)
    })

    it('resets verification loading when sending the challenge fails', async () => {
        getSpy.mockResolvedValue({ configs: [channel] })
        createSpy.mockRejectedValue(new Error('queue unavailable'))
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.verifyForwarding(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.verifyingChannelId).toBeNull()
        expect(logic.values.verificationAwaitingChannelIds).toEqual([])
    })

    it('shows retry guidance when the forwarding challenge does not return', async () => {
        jest.useFakeTimers()
        getSpy.mockResolvedValue({ configs: [channel] })
        createSpy.mockResolvedValue({ ok: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.verifyForwarding(channel.id)
        await expectLogic(logic).toFinishAllListeners()
        await jest.advanceTimersByTimeAsync(33_000)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.verificationAwaitingChannelIds).toEqual([])
        expect(logic.values.verificationTimedOutChannelIds).toEqual([channel.id])
    })

    it('connects and disconnects the current user email', async () => {
        createSpy.mockResolvedValueOnce({ config: channel }).mockResolvedValueOnce({ ok: true })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.addEmailFormVisible).toBe(false)
        logic.actions.setAddEmailFormVisible(true)
        logic.actions.setEmailDraft(' CSM@Example.com ')
        logic.actions.connectEmail()
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenNthCalledWith(1, 'api/conversations/v1/email/connect', {
            from_email: 'csm@example.com',
            from_name: 'Casey Manager',
            kind: 'customer_communication',
            owner_id: 7,
        })
        expect(logic.values.channels).toEqual([channel])
        expect(logic.values.emailDraft).toBe('')
        expect(logic.values.addEmailFormVisible).toBe(false)
        expect(logic.values.connecting).toBe(false)
        expect(logic.values.expandedChannelIds).toEqual([channel.id])

        logic.actions.disconnectEmail(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenNthCalledWith(2, 'api/conversations/v1/email/disconnect', {
            config_id: channel.id,
        })
        expect(logic.values.channels).toEqual([])
        expect(logic.values.expandedChannelIds).toEqual([])
        expect(logic.values.disconnectingChannelId).toBeNull()
    })
})
