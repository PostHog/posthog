import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { BusinessKnowledgeTabs } from './BusinessKnowledgeTabs'

describe('BusinessKnowledgeTabs', () => {
    afterEach(() => {
        cleanup()
    })

    it('links Settings to the in-product settings scene', () => {
        render(<BusinessKnowledgeTabs activeTab="sources" />)

        expect(screen.getByText('Sources').closest('a')).toHaveAttribute('href', '/business-knowledge')
        expect(screen.getByText('Settings').closest('a')).toHaveAttribute('href', '/business-knowledge/settings')
    })
})
