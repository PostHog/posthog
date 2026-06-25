import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { CyclotronInvocationQueueParametersEmailType } from '../../../schema/cyclotron'
import { parseJSON } from '../../../utils/json-parse'
import { createExampleInvocation } from '../../_tests/fixtures'
import { MessageAssetRow, MessageAssetsService } from './message-assets.service'

const mockS3Send = jest.fn()

jest.mock('@aws-sdk/client-s3', () => ({
    S3Client: jest.fn().mockImplementation(() => ({ send: mockS3Send })),
    PutObjectCommand: jest.fn().mockImplementation((input) => ({ __command: 'PutObject', input })),
}))

const CONFIG = {
    MESSAGE_ASSETS_CAPTURE_ENABLED: true,
    MESSAGE_ASSETS_OBJECT_STORAGE_ENDPOINT: 'http://objectstorage:19000',
    MESSAGE_ASSETS_OBJECT_STORAGE_REGION: 'us-east-1',
    MESSAGE_ASSETS_OBJECT_STORAGE_BUCKET: 'posthog',
    MESSAGE_ASSETS_OBJECT_STORAGE_ACCESS_KEY_ID: 'key',
    MESSAGE_ASSETS_OBJECT_STORAGE_SECRET_ACCESS_KEY: 'secret',
    MESSAGE_ASSETS_OBJECT_STORAGE_FOLDER: 'message_assets',
}

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

describe('MessageAssetsService', () => {
    let outputs: jest.Mocked<IngestionOutputs<'message_assets'>>
    let service: MessageAssetsService

    beforeEach(() => {
        jest.clearAllMocks()
        mockS3Send.mockResolvedValue({})
        outputs = buildOutputsMock()
        service = new MessageAssetsService(outputs, CONFIG)
    })

    const producedRow = (): MessageAssetRow => {
        const call = outputs.produce.mock.calls[0]
        const value = (call[1] as { value: Buffer }).value
        return parseJSON(value.toString('utf8')) as MessageAssetRow
    }

    it('writes the HTML to object storage and produces a metadata row for a sent email', async () => {
        const invocation = createExampleInvocation({ id: 'flow-1', team_id: 7 })
        invocation.state.actionId = 'email-step'

        await service.captureSentEmail(invocation, emailParams())

        expect(mockS3Send).toHaveBeenCalledTimes(1)
        const putInput = mockS3Send.mock.calls[0][0].input
        const expectedKey = `message_assets/team-7/flow-1/${invocation.id}/email-step.html`
        expect(putInput.Key).toBe(expectedKey)
        expect(putInput.Body).toBe('<p>Hello</p>')
        expect(putInput.Bucket).toBe('posthog')

        expect(outputs.produce).toHaveBeenCalledTimes(1)
        const row = producedRow()
        expect(row.team_id).toBe(7)
        expect(row.function_id).toBe('flow-1')
        expect(row.invocation_id).toBe(invocation.id)
        expect(row.action_id).toBe('email-step')
        // An email step carries an action id, so it's attributed to the workflow.
        expect(row.function_kind).toBe('hog_flow')
        expect(row.kind).toBe('email')
        expect(row.status).toBe('sent')
        expect(row.recipient).toBe('recipient@example.com')
        expect(row.subject).toBe('Welcome aboard')
        expect(row.s3_key).toBe(expectedKey)
    })

    it('skips a standalone email send (no action id) — it would be unretrievable', async () => {
        const invocation = createExampleInvocation({ id: 'fn-1', team_id: 3 })

        await service.captureSentEmail(invocation, emailParams())

        expect(mockS3Send).not.toHaveBeenCalled()
        expect(outputs.produce).not.toHaveBeenCalled()
    })

    it('does nothing when capture is disabled', async () => {
        service = new MessageAssetsService(outputs, { ...CONFIG, MESSAGE_ASSETS_CAPTURE_ENABLED: false })

        await service.captureSentEmail(createExampleInvocation(), emailParams())

        expect(mockS3Send).not.toHaveBeenCalled()
        expect(outputs.produce).not.toHaveBeenCalled()
    })

    it('skips text-only emails (no HTML to snapshot)', async () => {
        await service.captureSentEmail(createExampleInvocation(), emailParams({ html: '' }))

        expect(mockS3Send).not.toHaveBeenCalled()
        expect(outputs.produce).not.toHaveBeenCalled()
    })

    it('never throws and skips the metadata row when the object-storage write fails', async () => {
        mockS3Send.mockRejectedValue(new Error('s3 down'))
        const invocation = createExampleInvocation()
        invocation.state.actionId = 'email-step'

        await expect(service.captureSentEmail(invocation, emailParams())).resolves.toBeUndefined()
        expect(mockS3Send).toHaveBeenCalledTimes(1)
        expect(outputs.produce).not.toHaveBeenCalled()
    })

    it('never throws when the Kafka produce fails after a successful write', async () => {
        outputs.produce.mockRejectedValue(new Error('kafka down'))
        const invocation = createExampleInvocation()
        invocation.state.actionId = 'email-step'

        await expect(service.captureSentEmail(invocation, emailParams())).resolves.toBeUndefined()
        expect(mockS3Send).toHaveBeenCalledTimes(1)
    })
})
