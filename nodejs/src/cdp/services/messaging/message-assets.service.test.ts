import {
    CyclotronInvocationQueueParametersEmailType,
    CyclotronInvocationQueueParametersSendPushNotificationType,
} from '~/cdp/schema/cyclotron'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MessageAssetRow } from '../../types'
import { MessageAssetsService } from './message-assets.service'

const buildOutputsMock = (): jest.Mocked<IngestionOutputs<'message_assets'>> =>
    ({ produce: jest.fn().mockResolvedValue(undefined) }) as unknown as jest.Mocked<IngestionOutputs<'message_assets'>>

const emailParams = (
    overrides: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType =>
    ({
        type: 'email',
        to: { email: 'recipient@example.com' },
        from: { integrationId: 1 },
        subject: 'Welcome aboard',
        text: 'plain text',
        html: '<p>Hello</p>',
        ...overrides,
    }) as CyclotronInvocationQueueParametersEmailType

const pushParams = (
    payloadOverrides: Record<string, unknown> = {}
): CyclotronInvocationQueueParametersSendPushNotificationType =>
    ({
        type: 'sendPushNotification',
        integrationIds: [1],
        distinctId: 'user-1',
        payload: {
            title: 'Your order shipped',
            body: 'Track it in the app',
            ...payloadOverrides,
        },
    }) as unknown as CyclotronInvocationQueueParametersSendPushNotificationType

const invocationWithAction = (id: string, teamId = 7): CyclotronJobInvocationHogFunction => {
    const invocation = createExampleInvocation({ id, team_id: teamId })
    invocation.state.actionId = 'email-step'
    return invocation
}

const resultWith = (assets: MessageAssetRow[]): CyclotronJobInvocationResult =>
    ({
        messageAssets: assets,
    }) as unknown as CyclotronJobInvocationResult

const producedRowAt = (outputs: jest.Mocked<IngestionOutputs<'message_assets'>>, index: number): MessageAssetRow => {
    const call = outputs.produce.mock.calls[index]
    const value = (call[1] as { value: Buffer }).value
    return parseJSON(value.toString('utf8')) as MessageAssetRow
}

describe('MessageAssetsService', () => {
    let outputs: jest.Mocked<IngestionOutputs<'message_assets'>>
    let service: MessageAssetsService

    beforeEach(() => {
        jest.clearAllMocks()
        outputs = buildOutputsMock()
        service = new MessageAssetsService(outputs)
    })

    describe('buildRowForEmail', () => {
        it('returns a populated row for an in-workflow email step', () => {
            const invocation = invocationWithAction('flow-1', 7)

            const row = service.buildRowForEmail(invocation, emailParams())

            expect(row).not.toBeNull()
            expect(row!.team_id).toBe(7)
            expect(row!.function_id).toBe('flow-1')
            expect(row!.invocation_id).toBe(invocation.id)
            expect(row!.action_id).toBe('email-step')
            expect(row!.function_kind).toBe('hog_flow')
            expect(row!.kind).toBe('email')
            expect(row!.status).toBe('sent')
            expect(row!.recipient).toBe('recipient@example.com')
            expect(row!.subject).toBe('Welcome aboard')
            expect(row!.html).toBe('<p>Hello</p>')
        })

        it('returns null for a standalone email send (no action id — unretrievable from the Assets API)', () => {
            const invocation = createExampleInvocation({ id: 'fn-1', team_id: 3 })

            const row = service.buildRowForEmail(invocation, emailParams())

            expect(row).toBeNull()
        })

        it('wraps the text body in a <pre> when the email has no HTML, so plain-text sends still surface in the Assets tab', () => {
            const row = service.buildRowForEmail(
                invocationWithAction('flow-1'),
                emailParams({ html: '', text: 'hi <bob> & co' })
            )

            expect(row).not.toBeNull()
            // The raw `<`/`>`/`&` from the text body are HTML-escaped so they can't
            // break the surrounding <pre> markup or inject anything.
            expect(row!.html).toContain('<pre')
            expect(row!.html).toContain('hi &lt;bob&gt; &amp; co')
            expect(row!.html).not.toContain('hi <bob>')
        })

        it('returns null when both HTML and text bodies are empty', () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams({ html: '', text: '' }))

            expect(row).toBeNull()
        })

        it('substitutes a placeholder body when the rendered HTML exceeds the Kafka message-size budget', () => {
            // 5 MiB of 'a' — comfortably over the 4 MiB threshold. If we let this through the
            // producer would blow up mid-flush, take the whole batch's Promise.all with it, and
            // the "View email" chip would 404 for every recipient in that batch.
            const oversized = 'a'.repeat(5 * 1024 * 1024)

            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams({ html: oversized }))

            expect(row).not.toBeNull()
            expect(row!.html).not.toContain('a'.repeat(1024))
            expect(row!.html).toContain('Email too large to capture')
            // Everything else on the row must be preserved so the tab shows the correct
            // recipient/subject/timing even when the body itself was too big.
            expect(row!.recipient).toBe('recipient@example.com')
            expect(row!.subject).toBe('Welcome aboard')
        })
    })

    describe('buildRowForPush', () => {
        it('names the person as the recipient, matching how email fills that column', () => {
            // The Assets tab shows `recipient` as its RECIPIENT column, and for email that is the
            // address — so a push has to name who it reached, not which providers carried it.
            const row = service.buildRowForPush(invocationWithAction('flow-1', 7), pushParams(), ['Firebase', 'APNs'])

            expect(row).not.toBeNull()
            expect(row!.kind).toBe('push')
            expect(row!.team_id).toBe(7)
            expect(row!.subject).toBe('Your order shipped')
            expect(row!.recipient).toBe(row!.distinct_id)
            expect(row!.recipient).not.toBe('Firebase, APNs')
            expect(row!.status).toBe('sent')
            expect(row!.html).toContain('Your order shipped')
            expect(row!.html).toContain('Track it in the app')
            // The delivering channels are not part of what the recipient saw, so they stay out of the
            // snapshot for the same reason the custom `data` payload does.
            expect(row!.html).not.toContain('Firebase')
        })

        it('captures nothing when the push reached no device', () => {
            // An asset is a snapshot of what a recipient received, so a send that reached nobody has
            // nothing to show — it would render as an ordinary row with a blank recipient. The attempt
            // stays visible through the `push_skipped` metric and the run log explaining why.
            const row = service.buildRowForPush(invocationWithAction('flow-1'), pushParams(), [])

            expect(row).toBeNull()
        })

        it('renders the iOS subtitle, which the recipient sees as a second line', () => {
            // Delivered via the APNS alert, so a snapshot without it doesn't match the notification
            // that actually arrived on the device.
            const row = service.buildRowForPush(
                invocationWithAction('flow-1'),
                pushParams({ apns: { subtitle: 'Your account is ready' } }),
                ['APNs']
            )

            expect(row!.html).toContain('Your account is ready')
        })

        it('keeps the custom data payload out of the stored preview', () => {
            // `data` is app routing context rather than something the recipient saw, and can carry
            // arbitrary customer values we should not re-render in the UI.
            const row = service.buildRowForPush(
                invocationWithAction('flow-1'),
                pushParams({ data: { internal_ref: 'super-secret-value' } }),
                ['Firebase']
            )

            expect(row!.html).not.toContain('super-secret-value')
        })

        it('escapes notification content so a crafted title cannot inject markup into the viewer', () => {
            const row = service.buildRowForPush(
                invocationWithAction('flow-1'),
                pushParams({ title: '<img src=x onerror=alert(1)>' }),
                ['Firebase']
            )

            expect(row!.html).not.toContain('<img src=x')
            expect(row!.html).toContain('&lt;img src=x')
        })

        it('returns null for a push sent outside a workflow step, which the Assets API cannot retrieve', () => {
            const invocation = invocationWithAction('flow-1')
            invocation.state.actionId = undefined

            expect(service.buildRowForPush(invocation, pushParams(), ['Firebase'])).toBeNull()
        })
    })

    describe('queueInvocationResults + flush', () => {
        it('does not produce anything until flush is called', () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!

            service.queueInvocationResults([resultWith([row])])

            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('bulk-produces every queued row on flush', async () => {
            const row1 = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            const row2 = service.buildRowForEmail(invocationWithAction('flow-2'), emailParams({ subject: 'Second' }))!

            service.queueInvocationResults([resultWith([row1]), resultWith([row2])])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(2)
            const subjects = [producedRowAt(outputs, 0).subject, producedRowAt(outputs, 1).subject].sort()
            expect(subjects).toEqual(['Second', 'Welcome aboard'])
        })

        it('partitions each row by invocation_id so retries collapse via the ReplacingMergeTree', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!

            service.queueInvocationResults([resultWith([row])])
            await service.flush()

            const key = (outputs.produce.mock.calls[0][1] as { key: Buffer }).key
            expect(key.toString('utf8')).toBe(row.invocation_id)
        })

        it('clears the buffer after a successful flush so a second flush is a no-op', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            service.queueInvocationResults([resultWith([row])])

            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)

            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })

        it('skips results that carry an empty messageAssets array', async () => {
            service.queueInvocationResults([resultWith([]), resultWith([])])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('swallows broker failure so the CDP consumer keeps making progress', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            outputs.produce.mockRejectedValueOnce(new Error('kafka down'))

            service.queueInvocationResults([resultWith([row])])

            // No throw — the surrounding consumer batch must not be aborted just
            // because a few asset rows didn't make it to Kafka.
            await expect(service.flush()).resolves.toBeUndefined()
        })

        it('drops the buffer on flush failure so the next flush does not retry the failed rows', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            outputs.produce.mockRejectedValueOnce(new Error('kafka down'))

            service.queueInvocationResults([resultWith([row])])
            await service.flush()

            // Second flush with no new queuing is a no-op — failed rows are gone,
            // we don't get a second produce attempt against the broker.
            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })
    })
})
