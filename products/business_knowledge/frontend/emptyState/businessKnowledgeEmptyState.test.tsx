import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { businessKnowledgeEmptyState } from './businessKnowledgeEmptyState'

describe('businessKnowledgeEmptyState', () => {
    afterEach(() => {
        cleanup()
    })

    it('keeps Libraries and Settings reachable before any source exists', () => {
        const SceneNav = businessKnowledgeEmptyState.SceneNav
        if (!SceneNav) {
            throw new Error('SceneNav is missing')
        }
        render(<SceneNav />)

        expect(screen.getByText('Libraries').closest('a')).toHaveAttribute('href', '/business-knowledge')
        expect(screen.getByText('Settings').closest('a')).toHaveAttribute('href', '/business-knowledge/settings')
    })
})
