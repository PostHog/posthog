import React from 'react'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { PersonHeader } from 'scenes/persons/PersonHeader'

jest.mock('lib/api')

describe('the person component', () => {
    it('shows user without email', async () => {
        render(<PersonHeader person={{ properties: { name: 'Jane Doe' } }} />)

        expect(screen.getByRole('complementary')).toMatchSnapshot()
    })

    it('shows user without icon', async () => {
        render(<PersonHeader person={{ properties: { email: 'Jane.Doe@gmail.com' } }} />)

        expect(screen.getByRole('complementary')).toMatchSnapshot()
    })

    it('shows user with icon', async () => {
        render(
            <PersonHeader
                withIcon={true}
                person={{
                    properties: { email: 'Jane.Doe@gmail.com' },
                    distinct_ids: ['abcdefg'],
                }}
            />
        )

        expect(screen.getByRole('complementary')).toMatchSnapshot()
    })

    it('shows user with a link', async () => {
        render(
            <PersonHeader
                noLink={false}
                person={{ distinct_ids: ['abcdefg'], properties: { email: 'Jane.Doe@gmail.com' } }}
            />
        )

        expect(screen.getByTestId('person-header-link')).toMatchSnapshot()
    })
})
