import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { ExplainCSPViolationButton } from './ExplainCSPViolationButton'

const mockMarkdownProps: Record<string, any>[] = []

// Jest maps react-markdown to a stub that renders its children as plain text, so no <img> reaches
// the DOM to assert on. LemonMarkdown stands in for it here, which is where `disableImages` turns
// an untrusted image into a click-to-open link.
jest.mock('lib/lemon-ui/LemonMarkdown', () => ({
    LemonMarkdown: (props: Record<string, any>): null => {
        mockMarkdownProps.push(props)
        return null
    },
}))

describe('ExplainCSPViolationButton', () => {
    beforeEach(() => {
        initKeaTests()
        mockMarkdownProps.length = 0
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    // The explanation is written by a model fed a CSP report that anyone on the internet can post,
    // so an image URL inside it is attacker-chosen. Auto-loading it would fetch that URL when the
    // popover opens, handing the attacker the viewer's IP and user agent.
    it('renders the explanation with images disabled', async () => {
        jest.spyOn(api.cspReporting, 'explain').mockResolvedValue({
            response: 'Your policy blocks the script.\n\n![pixel](https://attacker.example.net/pixel.png)',
        })

        render(<ExplainCSPViolationButton properties={{}} label="Explain" />)
        fireEvent.click(screen.getByText('Explain'))

        await waitFor(() => expect(mockMarkdownProps).toHaveLength(1))
        expect(mockMarkdownProps[0].children).toContain('attacker.example.net')
        expect(mockMarkdownProps[0].disableImages).toBe(true)
    })

    // A refused request used to leave the popover open and empty, which reads the same as a broken
    // feature and gives the engineer nothing to act on.
    it('shows a message when the request fails', async () => {
        jest.spyOn(api.cspReporting, 'explain').mockRejectedValue(new Error('Bad Request'))

        render(<ExplainCSPViolationButton properties={{}} label="Explain" />)
        fireEvent.click(screen.getByText('Explain'))

        await waitFor(() => expect(screen.getByText(/failed to get a CSP explanation/)).toBeInTheDocument())
    })
})
