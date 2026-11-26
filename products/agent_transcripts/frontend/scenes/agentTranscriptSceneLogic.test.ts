import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { UPLOAD_FAILED_EVENT, agentTranscriptSceneLogic } from './agentTranscriptSceneLogic'

const SUBMISSION_URL = '/api/organizations/:organization_id/agent_transcripts/submission/'
const START_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/start_upload/'
const COMPLETE_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/complete_upload/'

const MAX_SIZE_BYTES = 1024

const STORAGE_ACCEPTED_STATUS = 204
const STORAGE_REFUSED_STATUS = 403
const GATEWAY_ERROR_STATUS = 502

const NOT_STARTED: CustomerSubmissionStateApi = {
    status: null,
    agent: null,
    original_filename: null,
    submitted_at: null,
    review_message: null,
    retention_days: 14,
    max_size_bytes: MAX_SIZE_BYTES,
    allowed_extensions: ['.jsonl', '.json', '.md', '.txt'],
}

const PRESIGNED_UPLOAD = {
    upload_url: 'https://storage.example.com/bucket',
    form_fields: { key: 'agent_transcripts/staging/abc' },
    expires_in: 900,
}

function transcriptFile(name: string, sizeBytes: number): File {
    return new File(['x'.repeat(sizeBytes)], name, { type: 'text/plain' })
}

function errorBody(code: string, detail: string): Record<string, string | null> {
    return { type: 'validation_error', code, detail, attr: null }
}

interface StoredUpload {
    key: FormDataEntryValue | null
    fileName: string | null
}

describe('agentTranscriptSceneLogic', () => {
    let logic: ReturnType<typeof agentTranscriptSceneLogic.build>
    let startUploadRequests: number
    let storedUploads: StoredUpload[]

    function useUploadEndpointMocks(
        startUpload: [number, unknown],
        completeUpload: [number, unknown] = [200, { ...NOT_STARTED, status: 'submitted' }],
        storageStatus: number = STORAGE_ACCEPTED_STATUS
    ): void {
        startUploadRequests = 0
        storedUploads = []
        useMocks({
            get: { [SUBMISSION_URL]: () => [200, NOT_STARTED] },
            post: {
                [START_UPLOAD_URL]: () => {
                    startUploadRequests += 1
                    return startUpload
                },
                [COMPLETE_UPLOAD_URL]: () => completeUpload,
                [PRESIGNED_UPLOAD.upload_url]: async ({ request }) => {
                    if (storageStatus !== STORAGE_ACCEPTED_STATUS) {
                        return [storageStatus]
                    }

                    const form = await request.formData()
                    const file = form.get('file')
                    storedUploads.push({ key: form.get('key'), fileName: file instanceof File ? file.name : null })
                    return [storageStatus]
                },
            },
        })
    }

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'test' })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    async function mountAndUpload(file: File): Promise<void> {
        logic = agentTranscriptSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSubmissionSuccess'])

        logic.actions.selectAgent('claude_code')
        logic.actions.uploadTranscript(file)

        await expectLogic(logic).toFinishAllListeners()
    }

    it('sends the file to review and shows the new status', async () => {
        useUploadEndpointMocks([200, PRESIGNED_UPLOAD])

        await mountAndUpload(transcriptFile('session.jsonl', 10))

        expect(storedUploads).toEqual([{ key: PRESIGNED_UPLOAD.form_fields.key, fileName: 'session.jsonl' }])
        expect(logic.values).toMatchObject({
            uploadError: null,
            isUploading: false,
            submission: expect.objectContaining({ status: 'submitted' }),
        })
    })

    it.each<[string, () => void, string, string | RegExp]>([
        [
            'a secret found by the server',
            () => useUploadEndpointMocks([200, PRESIGNED_UPLOAD], [400, errorBody('contains_secret', 'It has a key.')]),
            'contains_secret',
            'It has a key.',
        ],
        [
            'a review already in progress',
            () => useUploadEndpointMocks([409, errorBody('invalid_state', 'Your transcript is in review.')]),
            'invalid_state',
            'Your transcript is in review.',
        ],
        [
            'storage the server cannot reach',
            () => useUploadEndpointMocks([503, errorBody('storage_unavailable', 'Try again in a few minutes.')]),
            'storage_unavailable',
            'Try again in a few minutes.',
        ],
        [
            'a refused upload to storage',
            () => useUploadEndpointMocks([200, PRESIGNED_UPLOAD], undefined, STORAGE_REFUSED_STATUS),
            'storage_upload_failed',
            /Check your connection/,
        ],
    ])('shows the reason for %s and records it', async (_, arrange, code, detail) => {
        arrange()

        await mountAndUpload(transcriptFile('session.jsonl', 10))

        expect(logic.values.uploadError).toEqual({ code, detail: expect.stringMatching(detail) })
        expect(logic.values.isUploading).toBe(false)
        expect(posthog.capture).toHaveBeenCalledWith(UPLOAD_FAILED_EVENT, { code, variant: 'test' })
    })

    it('shows the review status when the server commits the upload but its response is lost', async () => {
        useUploadEndpointMocks([200, PRESIGNED_UPLOAD])
        let committed = false
        useMocks({
            get: { [SUBMISSION_URL]: () => [200, committed ? { ...NOT_STARTED, status: 'submitted' } : NOT_STARTED] },
            post: {
                [COMPLETE_UPLOAD_URL]: () => {
                    committed = true
                    return [GATEWAY_ERROR_STATUS]
                },
            },
        })

        await mountAndUpload(transcriptFile('session.jsonl', 10))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.submission).toEqual(expect.objectContaining({ status: 'submitted' }))
    })

    it.each<[string, File, string]>([
        ['a file over the size limit', transcriptFile('session.jsonl', MAX_SIZE_BYTES + 1), 'too_large'],
        ['a file type the server refuses', transcriptFile('session.pdf', 10), 'unsupported_extension'],
        ['an empty file', transcriptFile('session.md', 0), 'empty'],
    ])('rejects %s before any request', async (_, file, code) => {
        useUploadEndpointMocks([200, PRESIGNED_UPLOAD])

        await mountAndUpload(file)

        expect(logic.values.uploadError?.code).toBe(code)
        expect(startUploadRequests).toBe(0)
    })
})
