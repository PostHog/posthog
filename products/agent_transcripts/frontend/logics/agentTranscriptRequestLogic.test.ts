import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { REQUEST_DISMISSED_EVENT, agentTranscriptRequestLogic } from './agentTranscriptRequestLogic'
import type { AgentTranscriptRequestStage } from './agentTranscriptRequestLogic'

const SUBMISSION_URL = '/api/organizations/:organization_id/agent_transcripts/submission/'

function submissionWith(status: CustomerSubmissionStateApi['status']): CustomerSubmissionStateApi {
    return {
        status,
        agent: status ? 'claude_code' : null,
        original_filename: null,
        submitted_at: null,
        review_message: null,
        retention_days: 14,
        max_size_bytes: 25 * 1024 * 1024,
        allowed_extensions: ['.jsonl', '.json', '.md', '.txt'],
    }
}

describe('agentTranscriptRequestLogic', () => {
    let logic: ReturnType<typeof agentTranscriptRequestLogic.build>
    let submissionRequests: number

    function useSubmissionMock(status: CustomerSubmissionStateApi['status']): void {
        submissionRequests = 0
        useMocks({
            get: {
                [SUBMISSION_URL]: () => {
                    submissionRequests += 1
                    return [200, submissionWith(status)]
                },
            },
        })
    }

    async function mountWithFlag(flagValue: string | boolean): Promise<void> {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: flagValue })

        logic = agentTranscriptRequestLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.spyOn(posthog, 'capture')
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each<
        [
            string,
            string | boolean,
            CustomerSubmissionStateApi['status'],
            AgentTranscriptRequestStage | null,
            boolean,
            boolean,
        ]
    >([
        ['asks the control arm when nothing is uploaded', 'control', null, null, false, true],
        ['asks the test arm when an upload is pending', 'test', 'pending_upload', null, false, true],
        ['asks again when the team requested changes', 'control', 'changes_requested', null, false, true],
        ['does not ask when the flag is off', false, null, null, false, false],
        ['does not ask for a variant outside the experiment', 'holdout', null, null, false, false],
        ['does not ask while the transcript is in review', 'control', 'submitted', null, false, false],
        ['does not ask after approval', 'test', 'approved', null, false, false],
        ['does not ask after a decline', 'control', 'declined', null, false, false],
        ['stays hidden after a dismissal', 'control', null, 'request', false, false],
        [
            'ignores an earlier dismissal once changes are requested',
            'test',
            'changes_requested',
            'request',
            false,
            true,
        ],
        [
            'stays hidden after the changes request is dismissed',
            'test',
            'changes_requested',
            'changes_requested',
            false,
            false,
        ],
        ['hides on the submission page', 'control', 'pending_upload', null, true, false],
    ])('%s', async (_, flagValue, status, dismissedStage, onSubmissionPage, expected) => {
        useSubmissionMock(status)
        if (onSubmissionPage) {
            router.actions.push(urls.agentTranscript())
        }

        await mountWithFlag(flagValue)
        if (dismissedStage) {
            logic.actions.markDismissed(MOCK_DEFAULT_ORGANIZATION.id, dismissedStage)
        }

        expect(logic.values.shouldShowRequest).toBe(expected)
    })

    it('does not read the submission for an organization outside the experiment', async () => {
        useSubmissionMock(null)

        await mountWithFlag(false)

        expect(submissionRequests).toBe(0)
    })

    it('remembers a dismissal for the organization across page loads', async () => {
        useSubmissionMock(null)
        await mountWithFlag('test')

        logic.actions.dismissRequest()

        expect(posthog.capture).toHaveBeenCalledWith(REQUEST_DISMISSED_EVENT, { variant: 'test', stage: 'request' })

        logic.unmount()
        logic = agentTranscriptRequestLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.shouldShowRequest).toBe(false)
    })
})
