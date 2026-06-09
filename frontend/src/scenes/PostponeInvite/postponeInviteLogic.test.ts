import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { postponeInviteLogic } from './postponeInviteLogic'

interface PostBody {
    token: string
    send_at: string
}

describe('postponeInviteLogic', () => {
    let logic: ReturnType<typeof postponeInviteLogic.build>
    let lastPostBody: PostBody | undefined

    function mountWith(token: string): void {
        router.actions.push('/invite-postpone', { token })
        logic = postponeInviteLogic()
        logic.mount()
    }

    beforeEach(() => {
        lastPostBody = undefined
        useMocks({
            get: {
                '/api/invite_postpone': () => [
                    200,
                    {
                        organization_name: 'Acme Corp',
                        target_email: 'recipient@posthog.com',
                        inviter_first_name: 'Alice',
                        scheduled_send_at: null,
                        expires_at: '2026-06-10T00:00:00Z',
                    },
                ],
            },
            post: {
                '/api/invite_postpone': (req) => {
                    lastPostBody = req.body as PostBody
                    return [200, { scheduled_send_at: '2026-06-04T00:00:00Z', expires_at: '2026-06-07T00:00:00Z' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the invite info from the token on mount', async () => {
        mountWith('valid-token')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.invite?.organization_name).toEqual('Acme Corp')
        expect(logic.values.loadErrorMessage).toBeNull()
    })

    it('surfaces the error detail when the token is rejected', async () => {
        useMocks({
            get: {
                '/api/invite_postpone': () => [
                    400,
                    { detail: 'This link is invalid or has expired.', code: 'invalid_token' },
                ],
            },
        })
        mountWith('bad-token')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.invite).toBeNull()
        expect(logic.values.loadErrorMessage).toEqual('This link is invalid or has expired.')
    })

    it('postpones an hour out with a future timestamp', async () => {
        mountWith('valid-token')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.postponeByOption('hour')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.result).not.toBeNull()
        expect(dayjs(lastPostBody?.send_at).isAfter(dayjs())).toBe(true)
    })

    it('does not submit a custom postpone until a date is chosen', async () => {
        mountWith('valid-token')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.postponeCustom()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.result).toBeNull()
        expect(lastPostBody).toBeUndefined()
    })

    it('submits the chosen custom date', async () => {
        mountWith('valid-token')
        await expectLogic(logic).toFinishAllListeners()
        const target = dayjs().add(2, 'day')
        logic.actions.setCustomDate(target)
        logic.actions.postponeCustom()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.result).not.toBeNull()
        expect(dayjs(lastPostBody?.send_at).isSame(target)).toBe(true)
    })
})
