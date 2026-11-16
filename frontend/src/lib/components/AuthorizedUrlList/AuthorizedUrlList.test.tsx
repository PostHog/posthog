import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'

import { initKeaTests } from '~/test/init'

import { AuthorizedUrlList } from './AuthorizedUrlList'
import { AuthorizedUrlListType } from './authorizedUrlListLogic'

describe('AuthorizedUrlList', () => {
    afterEach(() => cleanup())

    // `app_urls` saves are admin-only on the backend, so a member must not get an Add button that only 403s.
    it.each([
        [AuthorizedUrlListType.WEB_ANALYTICS, OrganizationMembershipLevel.Member, 'true'],
        [AuthorizedUrlListType.WEB_ANALYTICS, OrganizationMembershipLevel.Admin, 'false'],
        [AuthorizedUrlListType.RECORDING_DOMAINS, OrganizationMembershipLevel.Member, 'false'],
    ])('for %s at level %s sets aria-disabled=%s on Add', (type, level, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, effective_membership_level: level })

        render(<AuthorizedUrlList type={type} displaySuggestions={false} hideEmptyState />)

        expect(screen.getByTestId('toolbar-add-url').getAttribute('aria-disabled')).toBe(expected)
    })
})
