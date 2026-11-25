import { cleanup, fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { makePersonListItem } from '../../people/testFixtures'
import { ExpensivePeopleSection, type ExpensivePeopleSectionProps } from './ExpensivePeopleSection'

const PEOPLE = [
    makePersonListItem({ id: 'p1', cost: 12 }),
    makePersonListItem({ id: 'p2', cost: 3 }),
    makePersonListItem({ id: 'p3', cost: null }),
]

function renderSection(props: Partial<ExpensivePeopleSectionProps> = {}): ReturnType<typeof render> {
    return render(
        <ExpensivePeopleSection
            people={PEOPLE}
            loading={false}
            failed={false}
            needsIdentification={false}
            docsUrl="https://example.com/docs"
            onRetry={jest.fn()}
            personHref={(person) => `/people?person=${person.id}`}
            viewAllHref="/people?order=cost"
            {...props}
        />
    )
}

describe('ExpensivePeopleSection', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it('links each row to its person and scales the bars to the top cost', () => {
        const { container } = renderSection()

        const links = Array.from(container.querySelectorAll('[data-attr="home-expensive-person"]'))
        expect(links.map((link) => link.getAttribute('href')?.replace('/project/997', ''))).toEqual([
            '/people?person=p1',
            '/people?person=p2',
            '/people?person=p3',
        ])
        const rows = links
        const bars = rows.map((row) => row.querySelector<HTMLElement>('[data-attr="home-expensive-person-bar"]'))
        expect(bars[0]?.style.width).toBe('100%')
        expect(bars[1]?.style.width).toBe('25%')
        expect(bars[2]).toBeNull()
        expect(rows[0].textContent).toContain('$12.00')
        expect(rows[2].textContent).toContain('-')
    })

    it('gives each row exactly one link', () => {
        const { container } = renderSection()

        for (const link of Array.from(container.querySelectorAll('[data-attr="home-expensive-person"]'))) {
            expect(link.querySelectorAll('a, button')).toHaveLength(0)
        }
    })

    it('shows the skeleton instead of rows while a reload is in flight', () => {
        const { container } = renderSection({ loading: true })

        expect(container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(0)
        expect(container.querySelector('.LemonSkeleton')).not.toBeNull()
    })

    it('links View all to the full list', () => {
        const { container } = renderSection()

        expect(container.querySelector('[data-attr="home-expensive-people-view-all"]')?.getAttribute('href')).toBe(
            '/project/997/people?order=cost'
        )
    })

    it('shows a skeleton while the people load', () => {
        const { container } = renderSection({ people: null })

        expect(container.querySelectorAll('[data-attr="home-expensive-person"]')).toHaveLength(0)
        expect(container.querySelector('.LemonSkeleton')).not.toBeNull()
    })

    it('offers a retry on a failed read instead of an empty list', () => {
        const onRetry = jest.fn()
        const { container, queryByText } = renderSection({ people: null, failed: true, onRetry })

        expect(queryByText('No people in this range')).toBeNull()
        fireEvent.click(container.querySelector('[data-attr="home-expensive-people-retry"]')!)
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    it('links to the docs when every person is anonymous', () => {
        const { container } = renderSection({ people: [], needsIdentification: true })

        expect(container.textContent).toContain('Not set up')
        expect(container.querySelector('[data-attr="home-expensive-people-not-set-up"]')?.getAttribute('href')).toBe(
            'https://example.com/docs'
        )
    })

    it('says so when the range holds no people', () => {
        const { queryByText } = renderSection({ people: [] })

        expect(queryByText('No people in this range')).not.toBeNull()
    })
})
