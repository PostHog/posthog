import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

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
        expect(await screen.findByText('Copy cell contents')).toBeInTheDocument()
    })

    it('closes an open copy menu when a non-copyable (empty) cell is right-clicked', async () => {
        render(
            <LemonTable
                enableCellCopy
                columns={[
                    { title: 'Name', dataIndex: 'name' },
                    { title: 'Blank', dataIndex: 'blank' },
                ]}
                dataSource={[{ name: 'All_callers', blank: '' }]}
            />
        )

        const nameCell = screen.getByText('All_callers').closest('td')!
        fireEvent.contextMenu(nameCell)
        expect(await screen.findByText('Copy cell contents')).toBeInTheDocument()

        // The Blank column's cell has no text, so right-clicking it must clear the open menu rather
        // than leave a stale popover pointing at the previous cell. The Popover unmounts its portal
        // on a delay, so wait for the button to leave the DOM.
        fireEvent.contextMenu(nameCell.nextElementSibling as HTMLElement)

        await waitFor(() => {
            expect(screen.queryByText('Copy cell contents')).not.toBeInTheDocument()
        })
    })
})
