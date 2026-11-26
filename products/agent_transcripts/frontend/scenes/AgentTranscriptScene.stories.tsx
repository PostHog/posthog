import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'

const SUBMISSION_URL = '/api/organizations/:organization_id/agent_transcripts/submission/'
const START_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/start_upload/'
const COMPLETE_UPLOAD_URL = '/api/organizations/:organization_id/agent_transcripts/complete_upload/'
const STORAGE_URL = '/storybook-object-storage/'

const NARROW_VIEWPORT = { width: 320, height: 1100 }

const NOT_STARTED: CustomerSubmissionStateApi = {
    status: null,
    agent: null,
    original_filename: null,
    submitted_at: null,
    review_message: null,
    retention_days: 14,
    max_size_bytes: 25 * 1024 * 1024,
    allowed_extensions: ['.jsonl', '.json', '.md', '.txt'],
}

const UPLOADED: CustomerSubmissionStateApi = {
    ...NOT_STARTED,
    agent: 'claude_code',
    original_filename: 'posthog-session-log.jsonl',
    submitted_at: '2026-11-18T10:30:00Z',
}

const REVIEW_MESSAGE =
    'Thanks for sending this. The file stops before the agent installed the SDK. Could you export the whole session, including the part where it added the snippet?'

const withSubmission = (submission: CustomerSubmissionStateApi): ReturnType<typeof mswDecorator> =>
    mswDecorator({ get: { [SUBMISSION_URL]: submission } })

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Agent transcripts',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-20',
        pageUrl: urls.agentTranscript(),
        featureFlags: { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'control' },
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            post: { '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Home' } },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

async function chooseAgent(canvasElement: HTMLElement, agentLabel: string): Promise<void> {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByRole('button', { name: agentLabel }))
}

async function uploadTranscript(canvasElement: HTMLElement): Promise<void> {
    await chooseAgent(canvasElement, 'Claude Code')

    const input = canvasElement.ownerDocument.querySelector<HTMLInputElement>('input[type="file"]')
    if (!input) {
        throw new Error('The upload input did not render')
    }
    await userEvent.upload(
        input,
        new File(['{"type":"user","message":"Set up PostHog"}'], 'posthog-session-log.jsonl', {
            type: 'application/jsonl',
        })
    )
}

export const NothingSubmitted: Story = {
    decorators: [withSubmission(NOT_STARTED)],
}

export const NothingSubmittedWithMerchCode: Story = {
    decorators: [withSubmission(NOT_STARTED)],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'test' },
    },
    play: async ({ canvasElement }) => {
        await chooseAgent(canvasElement, 'Claude Code')
    },
}

export const AppConversationInstructions: Story = {
    decorators: [withSubmission(NOT_STARTED)],
    play: async ({ canvasElement }) => {
        await chooseAgent(canvasElement, 'ChatGPT')
    },
}

export const Loading: Story = {
    decorators: [mswDecorator({ get: { [SUBMISSION_URL]: () => new Promise(() => {}) } })],
    parameters: {
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '[data-attr="agent-transcript-loading"]' },
    },
}

export const LoadError: Story = {
    decorators: [mswDecorator({ get: { [SUBMISSION_URL]: [500, { detail: 'Server error' }] } })],
}

export const Uploading: Story = {
    decorators: [
        mswDecorator({
            get: { [SUBMISSION_URL]: NOT_STARTED },
            post: {
                [START_UPLOAD_URL]: { upload_url: STORAGE_URL, form_fields: { key: 'staging' }, expires_in: 900 },
                [STORAGE_URL]: [204],
                [COMPLETE_UPLOAD_URL]: () => new Promise(() => {}),
            },
        }),
    ],
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
    play: async ({ canvasElement }) => {
        await uploadTranscript(canvasElement)
        await within(canvasElement).findByText('Checking the file')
    },
}

export const UploadRejectedForSecret: Story = {
    decorators: [
        mswDecorator({
            get: { [SUBMISSION_URL]: NOT_STARTED },
            post: {
                [START_UPLOAD_URL]: { upload_url: STORAGE_URL, form_fields: { key: 'staging' }, expires_in: 900 },
                [STORAGE_URL]: [204],
                [COMPLETE_UPLOAD_URL]: [
                    400,
                    {
                        type: 'validation_error',
                        code: 'contains_secret',
                        detail: 'The transcript contains what looks like a GitHub token. Remove it from the file, then upload the file again.',
                        attr: null,
                    },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await uploadTranscript(canvasElement)
        await within(canvasElement).findByText(/looks like a GitHub token/)
    },
}

export const InReview: Story = {
    decorators: [withSubmission({ ...UPLOADED, status: 'submitted' })],
}

export const ChangesRequested: Story = {
    decorators: [withSubmission({ ...UPLOADED, status: 'changes_requested', review_message: REVIEW_MESSAGE })],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'test' },
    },
}

export const ChangesRequestedNarrow: Story = {
    decorators: [withSubmission({ ...UPLOADED, status: 'changes_requested', review_message: REVIEW_MESSAGE })],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'test' },
        testOptions: { viewport: NARROW_VIEWPORT },
    },
}

export const ApprovedWithMerchCode: Story = {
    decorators: [withSubmission({ ...UPLOADED, status: 'approved' })],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.AGENT_TRANSCRIPT_REQUEST]: 'test' },
    },
}

export const Approved: Story = {
    decorators: [withSubmission({ ...UPLOADED, status: 'approved' })],
}

export const Declined: Story = {
    decorators: [
        withSubmission({
            ...UPLOADED,
            status: 'declined',
            review_message: 'The file is a summary of the setup rather than the conversation itself.',
        }),
    ],
}
