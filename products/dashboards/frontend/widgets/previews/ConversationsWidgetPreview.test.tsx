import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { ConversationsWidgetPreview } from './ConversationsWidgetPreview'

describe('ConversationsWidgetPreview', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('renders the Support ticket row preview from the shared widget samples', () => {
        render(<ConversationsWidgetPreview />)

        expect(screen.getByText('Jordan Lee')).toBeInTheDocument()
        expect(screen.getByText(/I can't invite a teammate to our project/)).toBeInTheDocument()
        expect(screen.getByText('critical')).toBeInTheDocument()
        expect(screen.getByText('Morgan Chen')).toBeInTheDocument()
    })
})
