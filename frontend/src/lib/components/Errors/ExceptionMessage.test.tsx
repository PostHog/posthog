import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { ExceptionMessage } from './ExceptionMessage'

describe('ExceptionMessage', () => {
    afterEach(cleanup)

    const cases: [string, string[]][] = [
        ['Error without a URL', []],
        ['Read https://react.dev/errors/418.', ['https://react.dev/errors/418']],
        ['Read http://docs.example.com/help.', ['http://docs.example.com/help']],
        ['Read https://posthog.com@docs.example.com/help.', []],
        ['Read https://user:password@docs.example.com/help.', []],
        ['Read https://:password@docs.example.com/help.', []],
        ['Read https://[invalid/help.', []],
        [
            'Read https://user@docs.example.com/help or https://docs.example.com/help.',
            ['https://docs.example.com/help'],
        ],
    ]

    it.each(cases)('preserves the message and links only plain HTTP(S) URLs: %s', (value, expectedUrls) => {
        const { container } = render(<ExceptionMessage value={value} />)

        const links = screen.queryAllByRole('link')
        expect(container.textContent).toBe(value)
        expect(links.map((link) => link.getAttribute('href'))).toEqual(expectedUrls)
        expect(links.map((link) => link.getAttribute('title'))).toEqual(expectedUrls)
    })
})
