import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { QuillMemberRolesPicker } from './QuillMemberRolesPicker'

describe('QuillMemberRolesPicker', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders its roles field', () => {
        render(<QuillMemberRolesPicker userUuid="user-1" />)

        expect(screen.getByLabelText('Roles')).toBeInTheDocument()
    })
})
