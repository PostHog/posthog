import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

import { CompareFilter } from './CompareFilter'

function renderWithInherit(compareFilter: CompareFilterType | null | undefined): void {
    render(
        <CompareFilter
            compareFilter={compareFilter}
            updateCompareFilter={jest.fn()}
            inheritLabel="Inherit from dashboard"
            onInherit={jest.fn()}
        />
    )
}

describe('CompareFilter', () => {
    afterEach(() => {
        cleanup()
    })

    describe('without inherit props (existing Insight view usage)', () => {
        it('offers only the three original options, with no fourth "inherit" entry', async () => {
            render(<CompareFilter compareFilter={null} updateCompareFilter={jest.fn()} />)

            await userEvent.click(screen.getByRole('button'))

            expect(screen.getByText('No comparison between periods')).toBeInTheDocument()
            expect(screen.getByText('Compare to previous period')).toBeInTheDocument()
            expect(screen.queryByText(/inherit/i)).not.toBeInTheDocument()
        })

        it('selecting "previous period" still calls updateCompareFilter, unchanged', async () => {
            const updateCompareFilter = jest.fn()
            render(<CompareFilter compareFilter={null} updateCompareFilter={updateCompareFilter} />)

            await userEvent.click(screen.getByRole('button'))
            await userEvent.click(screen.getByText('Compare to previous period'))

            expect(updateCompareFilter).toHaveBeenCalledWith({ compare: true, compare_to: undefined })
        })
    })

    describe('with inherit props supplied', () => {
        it.each([
            ['null', null, true],
            ['undefined', undefined, true],
            ['explicitly no comparison', { compare: false }, false],
        ] as const)('selects inherit exactly when compareFilter is %s', (_name, compareFilter, expectInherit) => {
            renderWithInherit(compareFilter)

            if (expectInherit) {
                expect(screen.getByRole('button')).toHaveTextContent('Inherit from dashboard')
            } else {
                expect(screen.getByRole('button')).not.toHaveTextContent('Inherit from dashboard')
            }
        })

        it('does not render the inherit option when inheritLabel is missing, even with onInherit set', async () => {
            render(<CompareFilter compareFilter={null} updateCompareFilter={jest.fn()} onInherit={jest.fn()} />)

            await userEvent.click(screen.getByRole('button'))

            expect(screen.queryByText(/inherit/i)).not.toBeInTheDocument()
        })

        it('selecting the inherit option calls onInherit instead of updateCompareFilter', async () => {
            const onInherit = jest.fn()
            const updateCompareFilter = jest.fn()
            render(
                <CompareFilter
                    compareFilter={{ compare: true, compare_to: undefined }}
                    updateCompareFilter={updateCompareFilter}
                    inheritLabel="Inherit from dashboard"
                    onInherit={onInherit}
                />
            )

            await userEvent.click(screen.getByRole('button'))
            await userEvent.click(screen.getByText('Inherit from dashboard'))

            expect(onInherit).toHaveBeenCalledTimes(1)
            expect(updateCompareFilter).not.toHaveBeenCalled()
        })
    })
})
