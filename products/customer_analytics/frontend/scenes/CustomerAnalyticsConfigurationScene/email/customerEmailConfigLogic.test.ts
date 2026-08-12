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
    })

    it('loads only customer communication channels', async () => {
        getSpy.mockResolvedValue({ configs: [channel] })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(getSpy).toHaveBeenCalledWith('api/conversations/v1/email/status?kind=customer_communication')
        expect(logic.values.channels).toEqual([channel])
        expect(logic.values.channelsLoading).toBe(false)
    })

    it('opens an authenticated confirmation and activates the channel', async () => {
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

        logic.actions.confirmForwarding(channel.id)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledWith('api/conversations/v1/email/confirm-forwarding', {
            config_id: channel.id,
        })
        expect(window.open).toHaveBeenCalledWith('about:blank', '_blank')
        expect(replace).toHaveBeenCalledWith('https://mail-settings.google.com/mail/vf-confirmation')
        expect(logic.values.channels[0]).toEqual({
            ...channel,
            connection_status: 'active',
            setup_expires_at: null,
            confirmation_available: false,
        })
        expect(logic.values.confirmingChannelId).toBeNull()
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
