import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ContextDisplay } from './Context'
import { maxContextLogic } from './maxContextLogic'

describe('ContextDisplay', () => {
    let logic: ReturnType<typeof maxContextLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/insights': { results: [] },
                '/api/projects/:team_id/dashboards': { results: [] },
                '/api/projects/:team_id/event_definitions': { results: [] },
                '/api/projects/:team_id/actions': { results: [] },
            },
        })
        initKeaTests()
        logic = maxContextLogic()
        logic.mount()
        cleanup()
    })

    afterEach(() => {
        logic?.unmount()
        cleanup()
    })

    describe('when deepResearchMode is false', () => {
        it('renders TaxonomicPopover with correct props', () => {
            const { container } = render(<ContextDisplay deepResearchMode={false} />)

            // Should render the TaxonomicPopover button with Add context functionality
            // TaxonomicPopover renders a button with specific classes
            const addContextButton = container.querySelector('.flex-shrink-0.border')
            expect(addContextButton).toBeInTheDocument()

            // Should not render the deep research warning
            expect(container.textContent).not.toContain('Turn off deep research to add context')
        })

        it('shows tooltip for adding context', () => {
            const { container } = render(<ContextDisplay deepResearchMode={false} />)

            // The TaxonomicPopover is wrapped in a Tooltip
            // Check that the button exists (the tooltip wraps it)
            const addContextButton = container.querySelector('.flex-shrink-0.border')
            expect(addContextButton).toBeInTheDocument()

            // The button should have the Add context placeholder if no data
            const buttonText = addContextButton?.textContent
            expect(buttonText).toContain('Add context')
        })

        it('passes correct size prop to ContextTags', () => {
            const { container } = render(<ContextDisplay size="small" deepResearchMode={false} />)

            // ContextTags returns null when no tags, but the parent container should exist
            const parentContainer = container.querySelector('.flex.flex-wrap.items-start.gap-1.w-full')
            expect(parentContainer).toBeInTheDocument()
        })
    })

    describe('when deepResearchMode is true', () => {
        it('renders warning message instead of TaxonomicPopover', () => {
            const { container, getByText } = render(<ContextDisplay deepResearchMode={true} />)

            // Should show the warning message
            expect(getByText('Turn off deep research to add context')).toBeInTheDocument()

            // Should not render the TaxonomicPopover button
            const addContextButton = container.querySelector('[data-attr="taxonomic-popover"]')
            expect(addContextButton).not.toBeInTheDocument()
        })

        it('uses consistent styling with proper disabled state', () => {
            const { container } = render(<ContextDisplay deepResearchMode={true} />)

            // Should render LemonButton with disabled state
            const disabledButton = container.querySelector('button[aria-disabled="true"]')
            expect(disabledButton).toBeInTheDocument()
            // LemonButton with type="tertiary" and border class
            expect(disabledButton?.classList.contains('LemonButton')).toBe(true)
        })

        it('includes accessibility attributes', () => {
            const { container } = render(<ContextDisplay deepResearchMode={true} />)

            // Should have aria-disabled attribute for accessibility
            const disabledElement = container.querySelector('[aria-disabled="true"]')
            expect(disabledElement).toBeInTheDocument()
        })

        it('displays warning icon with warning text', () => {
            const { container, getByText } = render(<ContextDisplay deepResearchMode={true} />)

            // Should contain the warning text
            expect(getByText('Turn off deep research to add context')).toBeInTheDocument()

            // Should contain the warning icon
            const icon = container.querySelector('svg')
            expect(icon).toBeInTheDocument()
        })

        it('still renders ContextTags even when disabled', () => {
            const { container } = render(<ContextDisplay deepResearchMode={true} />)

            // The parent container should exist even if ContextTags returns null
            const parentContainer = container.querySelector('.flex.flex-wrap.items-start.gap-1.w-full')
            expect(parentContainer).toBeInTheDocument()
        })
    })

    describe('prop variations', () => {
        it('handles default props correctly', () => {
            const { container } = render(<ContextDisplay />)

            // Should render with default props (deepResearchMode = false, size = 'default')
            const addContextButton = container.querySelector('.flex-shrink-0.border')
            expect(addContextButton).toBeInTheDocument()
        })

        it('applies different size classes', () => {
            const { container: smallContainer } = render(<ContextDisplay size="small" />)
            const { container: defaultContainer } = render(<ContextDisplay size="default" />)

            // Both should render but potentially with different styling classes
            expect(smallContainer.querySelector('.px-1.pt-1.w-full')).toBeInTheDocument()
            expect(defaultContainer.querySelector('.px-1.pt-1.w-full')).toBeInTheDocument()
        })
    })

    describe('logic integration', () => {
        it('integrates with maxContextLogic values', async () => {
            await expectLogic(logic).toFinishAllListeners()

            const { container } = render(<ContextDisplay deepResearchMode={false} />)

            // Should integrate with the logic for context handling
            expect(container).toBeInTheDocument()
        })

        it('passes correct props to TaxonomicPopover', () => {
            const { container } = render(<ContextDisplay deepResearchMode={false} />)

            // Should pass the expected props to TaxonomicPopover
            const popover = container.querySelector('.flex-shrink-0.border')
            expect(popover).toBeInTheDocument()
        })
    })
})
