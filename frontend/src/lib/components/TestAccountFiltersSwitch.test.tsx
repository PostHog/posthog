import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { TestAccountFilterSwitch, getUnusedTestAccountFilterReason } from './TestAccountFiltersSwitch'

describe('TestAccountFilterSwitch', () => {
    describe('gear icon links to internal test filtering settings', () => {
        beforeEach(() => {
            initKeaTests()
            featureFlagLogic.mount()
        })

        afterEach(() => {
            cleanup()
        })

        it('navigates to the customization settings, scrolled to internal-user-filtering', () => {
            render(<TestAccountFilterSwitch checked={false} onChange={jest.fn()} />)

            // The LemonSwitch itself has role="switch"; the gear is rendered as a link.
            // The router prepends a `/project/<id>` prefix to the href, so match the suffix.
            const gear = screen.getByRole('link')
            expect(gear.getAttribute('href')).toMatch(/\/settings\/environment-customization#internal-user-filtering$/)
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
