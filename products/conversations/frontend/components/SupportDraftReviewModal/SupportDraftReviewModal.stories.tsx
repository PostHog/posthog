import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { billingLogic } from 'lib/logic/billing/billingLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingType } from '~/types'

import type { PostHogSupportDraftApi } from '../../generated/api.schemas'
import { myTicketsSceneLogic } from '../../scenes/myTickets/myTicketsSceneLogic'
import { SupportDraftReviewModal } from './SupportDraftReviewModal'

const DRAFT: PostHogSupportDraftApi = {
    id: 'draft-1',
    message: [
        'Staging test events to delete from our live project',
        'Request:\n\nOur staging build sent test checkout events to our live project. Please delete the 3,817 events the query below returns.',
        'Details:\n- Project: Web app (ID 12345), US Cloud\n- Events: `checkout_started` from `staging.example.com`',
        'Already checked:\n- Claude Code checked: the query returns 3,817 events',
    ].join('\n\n---\n\n'),
    ticket_context: 'Drafted by an AI agent through the PostHog MCP, then reviewed and sent by the person.',
    expires_at: 0,
    billing_question: false,
    review_url: '',
    next_step: '',
}

function DraftUnderReview({ plan }: { plan: BillingType['subscription_level'] }): JSX.Element {
    useStorybookMocks({ get: { '/api/billing/': { ...billingJson, subscription_level: plan } } })
    useMountedLogic(billingLogic)
    useMountedLogic(myTicketsSceneLogic)

    useEffect(() => {
        supportLogic.actions.resetSendSupportRequest({
            name: '',
            email: '',
            kind: 'support',
            message: DRAFT.message,
            ticket_context: DRAFT.ticket_context,
            ai_draft_id: DRAFT.id,
        })
        myTicketsSceneLogic.actions.reviewDraft(DRAFT)
    }, [plan])

    return <SupportDraftReviewModal />
}

const meta: Meta<typeof DraftUnderReview> = {
    title: 'Scenes-App/Support/SupportDraftReviewModal',
    component: DraftUnderReview,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // One scene renders this modal, and no layout here has broken before, so render it without a baseline
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<typeof DraftUnderReview>

export const ReadyToSend: Story = { args: { plan: 'paid' } }

export const PlanWithoutTickets: Story = { args: { plan: 'free' } }
