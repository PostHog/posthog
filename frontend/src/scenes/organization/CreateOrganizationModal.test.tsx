import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
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

    // Regression guards: Enter used to submit an empty name, bypassing the button's disabledReason, and an
    // IME uses Enter to accept a candidate, so a composing Enter must not submit the unconverted text.
    it.each<[string, boolean, string[][]]>([
        ['', false, []],
        ['Acme Inc.', false, [['Acme Inc.']]],
        ['あくめ', true, []],
    ])('Enter with name %p while composing %p dispatches %p', async (typed, isComposing, expectedCalls) => {
        const { container } = render(<CreateOrganizationModal isVisible inline />)
        const input = getByDataAttr(container, 'organization-name-input')
        if (typed) {
            await userEvent.type(input, typed)
        }
        fireEvent.keyDown(input, { key: 'Enter', isComposing })
        expect(createOrganization.mock.calls).toEqual(expectedCalls)
    })
})
