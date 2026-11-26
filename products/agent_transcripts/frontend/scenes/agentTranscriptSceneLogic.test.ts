import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { StorageUploadError, postFileToStorage } from '../logics/postFileToStorage'
import { UPLOAD_FAILED_EVENT, agentTranscriptSceneLogic } from './agentTranscriptSceneLogic'

jest.mock('../logics/postFileToStorage', () => ({
    ...jest.requireActual('../logics/postFileToStorage'),
    postFileToStorage: jest.fn(),
}))

const postFileToStorageMock = postFileToStorage as jest.Mock

const SUBMISSION_URL = '/api/organizations/:organization_id/agent_transcripts/submission/'
const START_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/start_upload/'
const COMPLETE_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/complete_upload/'

const MAX_SIZE_BYTES = 1024

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

describe('agentTranscriptSceneLogic', () => {
    let logic: ReturnType<typeof agentTranscriptSceneLogic.build>
    let startUploadRequests: number

    function useUploadEndpointMocks(
        startUpload: [number, unknown],
        completeUpload: [number, unknown] = [200, { ...NOT_STARTED, status: 'submitted' }]
    ): void {
        startUploadRequests = 0
        useMocks({
            get: { [SUBMISSION_URL]: () => [200, NOT_STARTED] },
            post: {
                [START_UPLOAD_URL]: () => {
                    startUploadRequests += 1
                    return startUpload
                },
                [COMPLETE_UPLOAD_URL]: () => completeUpload,
            },
        })
    }

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        postFileToStorageMock.mockReset()
        postFileToStorageMock.mockResolvedValue(undefined)
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

        expect(postFileToStorageMock).toHaveBeenCalledWith(
            expect.objectContaining({ presignedUpload: PRESIGNED_UPLOAD })
        )
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
            () => {
                useUploadEndpointMocks([200, PRESIGNED_UPLOAD])
                postFileToStorageMock.mockRejectedValue(new StorageUploadError('refused'))
            },
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
