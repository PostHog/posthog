import { render, waitFor, within } from '@testing-library/react'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { OrganizationDeactivated } from './Deactivated'

describe('OrganizationDeactivated', () => {
    it.each([
        ['offers billing as a way out of the block', true, urls.organizationBilling()],
        ['offers no billing link when billing is not available', false, null],
    ])('%s', async (_name, cloud, expectedHref) => {
        useMocks({ get: { '/_preflight': { ...preflightJson, cloud } } })
        initKeaTests()
        await waitFor(() => expect(preflightLogic.values.preflight?.cloud).toBe(cloud))

        const { container } = render(<OrganizationDeactivated />)

        const link = within(container).queryByText('Go to billing')?.closest('a')
        expect(link?.getAttribute('href') ?? null).toBe(expectedHref)
    })
})
