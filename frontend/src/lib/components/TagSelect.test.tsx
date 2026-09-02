import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TagSelect } from './TagSelect'

function tagNames(count: number): string[] {
    return Array.from({ length: count }, (_, index) => `tag-${String(index).padStart(3, '0')}`)
}

describe('TagSelect', () => {
    let tags: string[]
    let onChange: jest.Mock

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/tags/': () => [200, tags] } })
        initKeaTests()
        onChange = jest.fn()
    })

    afterEach(() => {
        cleanup()
    })

    async function renderAndOpen(): Promise<void> {
        render(
            <Provider>
                <TagSelect value={[]} onChange={onChange} />
            </Provider>
        )
        await userEvent.click(screen.getByRole('button', { name: 'Any tags' }))
        await waitFor(() => expect(screen.getByText(tags[0])).toBeInTheDocument())
    }

    it('renders every option when there are few tags', async () => {
        tags = tagNames(5)
        await renderAndOpen()

        expect(screen.getAllByRole('menuitem')).toHaveLength(tags.length)
    })

    it('windows the list when a project has many tags', async () => {
        tags = tagNames(500)
        await renderAndOpen()

        // Only the visible slice is mounted — mounting all 500 is what made the dropdown slow to open
        expect(screen.getAllByRole('menuitem').length).toBeLessThan(50)
    })

    it('selects a tag when its option is clicked', async () => {
        tags = tagNames(5)
        await renderAndOpen()

        await userEvent.click(screen.getByText('tag-002'))

        expect(onChange).toHaveBeenCalledWith(['tag-002'])
    })
})
