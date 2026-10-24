import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { QuillInsightCardMenu, QuillInsightCardMenuProps } from './QuillInsightCardMenu'

const noop = (): void => {}

describe('QuillInsightCardMenu', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each<[string, Partial<QuillInsightCardMenuProps>, string[]]>([
        [
            'a dashboard editor',
            {
                onView: noop,
                onEdit: noop,
                onDuplicate: noop,
                onRename: noop,
                onSetColor: noop,
                onToggleDescription: noop,
                onRefresh: noop,
                onRemoveFromDashboard: noop,
            },
            ['View', 'Edit', 'Duplicate', 'Organize', 'Display', 'Data', 'Export', 'Remove from dashboard'],
        ],
        ['a viewer', { onView: noop, onDuplicate: noop }, ['View', 'Duplicate', 'Export']],
        [
            'an insight outside a dashboard',
            { onView: noop, onDeleteInsight: noop },
            ['View', 'Export', 'Delete insight'],
        ],
    ])('shows the top-level rows for %s', async (_, props, expectedRows) => {
        render(<QuillInsightCardMenu placementDestinations={[]} onCopyImage={noop} {...props} />)

        await userEvent.click(screen.getByRole('button', { name: 'More actions' }))

        const rows = (await screen.findAllByRole('menuitem')).map((row) => row.textContent?.trim())
        expect(rows).toEqual(expectedRows)
    })
})
