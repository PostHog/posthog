import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { organizationLogic } from 'scenes/organizationLogic'

import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'

import { CreateOrganizationModal } from './CreateOrganizationModal'

describe('<CreateOrganizationModal />', () => {
    let createOrganization: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        createOrganization = jest.spyOn(organizationLogic.actions, 'createOrganization')
    })

    afterEach(() => {
        createOrganization.mockRestore()
        cleanup()
    })

    // Regression guard: Enter used to submit an empty name, bypassing the button's disabledReason.
    it.each<[string, string[][]]>([
        ['', []],
        ['Acme Inc.', [['Acme Inc.']]],
    ])('Enter with name %p dispatches %p', async (typed, expectedCalls) => {
        const { container } = render(<CreateOrganizationModal isVisible inline />)
        await userEvent.type(getByDataAttr(container, 'organization-name-input'), `${typed}{Enter}`)
        expect(createOrganization.mock.calls).toEqual(expectedCalls)
    })
})
