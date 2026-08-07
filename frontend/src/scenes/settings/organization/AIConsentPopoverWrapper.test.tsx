import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { AIConsentPopoverWrapper } from './AIConsentPopoverWrapper'

const CONSENT_COPY = /needs your approval to potentially process/
const REQUEST_ACCESS_COPY = /has not been enabled for this organization/

describe('AIConsentPopoverWrapper', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    // The request-access variant is only correct for a member we know lacks admin rights. Admins,
    // owners, and the still-loading state (currentOrganization null) must all get the consent variant
    // — otherwise an org owner is falsely told AI "has not been enabled" and handed a request button
    // the backend rejects. The null case is the regression this guards: isAdminOrOwner is false while
    // the org loads, so keying the branch off it alone misclassifies every admin on first paint.
    it.each([
        { name: 'owner', level: OrganizationMembershipLevel.Owner, expectsAccessRequest: false },
        { name: 'admin', level: OrganizationMembershipLevel.Admin, expectsAccessRequest: false },
        { name: 'member', level: OrganizationMembershipLevel.Member, expectsAccessRequest: true },
        { name: 'still-loading org', level: null, expectsAccessRequest: false },
    ])('shows the right variant for $name', async ({ level, expectsAccessRequest }) => {
        if (level === null) {
            useMocks({ get: { '/api/organizations/@current': () => [200, null] } })
            initKeaTests(true, undefined, undefined, null as unknown as OrganizationType)
        } else {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                membership_level: level,
                is_ai_data_processing_approved: false,
            })
        }

        const { unmount } = render(
            <AIConsentPopoverWrapper ignoreDismissal>
                <button>Explain</button>
            </AIConsentPopoverWrapper>
        )

        const [expected, absent] = expectsAccessRequest
            ? [REQUEST_ACCESS_COPY, CONSENT_COPY]
            : [CONSENT_COPY, REQUEST_ACCESS_COPY]
        // findByText also lets floating-ui's async positioning settle before we tear the tree down.
        expect(await screen.findByText(expected)).toBeInTheDocument()
        expect(screen.queryByText(absent)).not.toBeInTheDocument()

        unmount()
    })
})
