import { PartnerReviewApi, PartnerReviewEventApi } from '~/generated/core/api.schemas'

import { reviewProgress } from './oauthAppProvisioningStatus'

const event = (
    kind: PartnerReviewEventApi['kind'],
    status: PartnerReviewEventApi['status'] = null
): PartnerReviewEventApi => ({
    at: '2026-01-10T10:00:00Z',
    kind,
    status,
    message: '',
    author: '',
})

const review = (status: PartnerReviewApi['status'], timeline: PartnerReviewEventApi[]): PartnerReviewApi => ({
    status,
    opened_at: '2026-01-10T10:00:00Z',
    decided_at: null,
    partner_message: '',
    timeline: [event('registered'), ...timeline],
})

describe('reviewProgress', () => {
    test.each([
        ['under automated review', review('pending', []), 'Registered, Automated review, Decision', 'automated_review'],
        [
            'approved by the automated review',
            review('accepted', [event('automated_review', 'accepted')]),
            'Registered, Automated review, Approved',
            'complete',
        ],
        [
            'declined by the automated review',
            review('declined', [event('automated_review', 'declined')]),
            'Registered, Automated review, Declined',
            'decision',
        ],
        [
            'waiting for staff',
            review('needs_human', [event('automated_review', 'needs_human')]),
            'Registered, Automated review, PostHog staff review, Decision',
            'staff_review',
        ],
        [
            'sent back by staff',
            review('changes_requested', [
                event('automated_review', 'needs_human'),
                event('staff_decision', 'changes_requested'),
            ]),
            'Registered, Automated review, PostHog staff review, Changes requested',
            'decision',
        ],
        [
            'asking again after an automated decline',
            review('needs_human', [event('automated_review', 'declined'), event('partner_note')]),
            'Registered, Automated review, PostHog staff review, Decision',
            'staff_review',
        ],
    ])('a review %s', (_name, reviewed, labels, currentStep) => {
        const progress = reviewProgress(reviewed)

        expect(progress.steps.map(({ label }) => label).join(', ')).toEqual(labels)
        expect(progress.currentStep).toEqual(currentStep)
    })
})
