import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { TestAccountFilterSwitch, getUnusedTestAccountFilterReason } from './TestAccountFiltersSwitch'

describe('TestAccountFilterSwitch', () => {
    describe('render branches', () => {
        beforeEach(() => {
            initKeaTests()
            featureFlagLogic.mount()
            teamLogic.mount()
        })

        afterEach(() => {
            cleanup()
        })

        it('links to settings instead of a dead switch when no filters are configured', () => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, test_account_filters: [] })
            render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} />)

            expect(screen.queryByRole('switch')).not.toBeInTheDocument()
            // The router prepends a `/project/<id>` prefix to the href, so match the suffix.
            const link = screen.getByRole('link')
            expect(link.getAttribute('href')).toMatch(/\/settings\/environment-customization#internal-user-filtering$/)
        })

        it('keeps the setup control disabled, not a live link, when the caller passes a disabledReason', () => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, test_account_filters: [] })
            render(
                <TestAccountFilterSwitch
                    checked={false}
                    onChange={jest.fn()}
                    disabledReason="Filter groups cannot be added to insights with a data warehouse series."
                />
            )

            // A disabled control renders as a non-navigable button, so the misleading "go set it up"
            // link is gone and the button reports itself disabled.
            expect(screen.queryByRole('link')).not.toBeInTheDocument()
            expect(screen.getByRole('button')).toHaveAttribute('aria-disabled', 'true')
        })

        it('shows a switch reflecting the real checked value when filters exist', () => {
            teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
            render(<TestAccountFilterSwitch checked={true} onChange={jest.fn()} />)

            expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
        })
    })

    describe('getUnusedTestAccountFilterReason', () => {
        // Guards that the toggle isn't a silent no-op: it should report "unused" (a non-null reason,
        // which disables the switch) exactly when the team has filters but none apply to the surface.
        it.each([
            ['cohort surface, only event filters', [{ type: 'event' }], ['person'], true],
            ['cohort surface, only a cohort filter', [{ type: 'cohort' }], ['person'], true],
            [
                'persons surface, only event + hogql filters',
                [{ type: 'event' }, { type: 'hogql' }],
                ['person', 'cohort'],
                true,
            ],
            ['cohort surface, a person filter applies', [{ type: 'person' }], ['person'], false],
            [
                'cohort surface, at least one person filter among others',
                [{ type: 'event' }, { type: 'person' }],
                ['person'],
                false,
            ],
            ['persons surface, a cohort filter applies', [{ type: 'cohort' }], ['person', 'cohort'], false],
            ['no filters configured', [], ['person'], false],
        ])('%s', (_name, filters, applicableTypes, expectUnused) => {
            const reason = getUnusedTestAccountFilterReason(filters, applicableTypes)
            expect(reason !== null).toBe(expectUnused)
        })

        it('names the applicable filter types in the reason', () => {
            expect(getUnusedTestAccountFilterReason([{ type: 'event' }], ['person'])).toBe(
                'Only person property filters from your internal and test account settings apply here.'
            )
            expect(getUnusedTestAccountFilterReason([{ type: 'event' }], ['person', 'cohort'])).toBe(
                'Only person property and cohort filters from your internal and test account settings apply here.'
            )
        })
    })
})
