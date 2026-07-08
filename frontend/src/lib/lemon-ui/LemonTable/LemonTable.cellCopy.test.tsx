import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { extractCellText, LemonTable } from './LemonTable'

interface Row {
    name: string
}

const dataSource: Row[] = [{ name: 'All_callers' }]

/** Build a detached `<td>` with the given inner HTML so `extractCellText` can be tested in isolation. */
function cellWith(innerHTML: string): HTMLElement {
    const td = document.createElement('td')
    td.innerHTML = innerHTML
    return td
}

describe('extractCellText', () => {
    it('returns the plain text of a scalar cell', () => {
        expect(extractCellText(cellWith('All_callers'))).toBe('All_callers')
    })

    it('recovers text clipped by CSS ellipsis (full textContent is in the DOM)', () => {
        expect(extractCellText(cellWith('<span class="truncate">a-very-long-distinct-id-0199</span>'))).toBe(
            'a-very-long-distinct-id-0199'
        )
    })

    it('joins visually-separated children with a space instead of smushing', () => {
        // `textContent` alone would yield "FooBar" — CSS spacing between siblings is not text.
        expect(extractCellText(cellWith('<span>Foo</span><span>Bar</span>'))).toBe('Foo Bar')
    })

    it('collapses internal whitespace and trims', () => {
        expect(extractCellText(cellWith('  <span>Enabled</span>\n  <span>Stale</span>  '))).toBe('Enabled Stale')
    })

    it('returns an empty string for an empty cell', () => {
        expect(extractCellText(cellWith(''))).toBe('')
    })
})

describe('LemonTable enableCellCopy gating', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('does not offer "Copy cell contents" on right-click unless enableCellCopy is set', () => {
        render(<LemonTable columns={[{ title: 'Name', dataIndex: 'name' }]} dataSource={dataSource} />)

        fireEvent.contextMenu(screen.getByText('All_callers').closest('td')!)

        expect(screen.queryByText('Copy cell contents')).not.toBeInTheDocument()
    })

    it('offers "Copy cell contents" on right-click when enableCellCopy is set', async () => {
        render(<LemonTable enableCellCopy columns={[{ title: 'Name', dataIndex: 'name' }]} dataSource={dataSource} />)

        fireEvent.contextMenu(screen.getByText('All_callers').closest('td')!)

        // The popover only mounts its overlay when visible, so finding the button proves the
        // right-click handler fired and opened the copy affordance.
        expect(await screen.findByRole('button', { name: 'Copy cell contents' })).toBeInTheDocument()
    })
})
