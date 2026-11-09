import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill-primitives'

import { FilterSearchSubMenu } from './filter-menu'

describe('FilterSearchSubMenu', () => {
    afterEach(cleanup)

    it('keeps the selection when Escape dismisses the submenu', async () => {
        const onChange = jest.fn()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filters</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={[
                            { value: 'growth', label: 'growth' },
                            { value: 'revenue', label: 'revenue' },
                        ]}
                        selected={['growth']}
                        onChange={onChange}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )

        await act(async () => {
            fireEvent.click(await screen.findByText('Tags'))
        })
        const input = await screen.findByLabelText('Search tags')

        fireEvent.keyDown(input, { key: 'Escape' })

        expect(onChange).not.toHaveBeenCalled()
    })

    it('calls onOpen when the submenu opens', async () => {
        const onOpen = jest.fn()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filters</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={[]}
                        selected={[]}
                        onChange={jest.fn()}
                        onOpen={onOpen}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
        const row = await screen.findByText('Tags')
        expect(onOpen).not.toHaveBeenCalled()

        await act(async () => {
            fireEvent.click(row)
        })

        expect(onOpen).toHaveBeenCalledTimes(1)
    })

    it('caps the rows until a search narrows them', async () => {
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filters</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={Array.from({ length: 300 }, (_, index) => ({
                            value: `tag-${index}`,
                            label: `tag-${index}`,
                        }))}
                        selected={[]}
                        onChange={jest.fn()}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
        await act(async () => {
            fireEvent.click(await screen.findByText('Tags'))
        })
        const input = await screen.findByLabelText('Search tags')

        // The "Any tag" row and the first 200 options.
        expect(screen.getAllByRole('menuitemcheckbox')).toHaveLength(201)
        expect(screen.getByText('Keep typing to see more')).toBeTruthy()
        expect(screen.queryByText('tag-299')).toBeNull()

        await act(async () => {
            fireEvent.change(input, { target: { value: 'tag-299' } })
        })

        expect(screen.getAllByRole('menuitemcheckbox').map((row) => row.textContent)).toEqual(['tag-299'])
        expect(screen.queryByText('Keep typing to see more')).toBeNull()
    })

    it('reports how long the submenu took to open', async () => {
        const onOpened = jest.fn()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filters</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={[]}
                        selected={[]}
                        onChange={jest.fn()}
                        onOpened={onOpened}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )

        await act(async () => {
            fireEvent.click(await screen.findByText('Tags'))
        })

        await waitFor(() => expect(onOpened).toHaveBeenCalledTimes(1))
        expect(onOpened).toHaveBeenCalledWith({ durationMs: expect.any(Number), optionCount: 0 })
    })

    it('adds a picked row to the selection and keeps the menu open', async () => {
        const onChange = jest.fn()
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuTrigger>Filters</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <FilterSearchSubMenu
                        label="Tags"
                        allLabel="Any tag"
                        pluralNoun="tags"
                        options={[
                            { value: 'growth', label: 'growth' },
                            { value: 'revenue', label: 'revenue' },
                        ]}
                        selected={['growth']}
                        onChange={onChange}
                        searchPlaceholder="Search tags"
                        emptyText="No tag matches"
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
        await act(async () => {
            fireEvent.click(await screen.findByText('Tags'))
        })
        const input = await screen.findByLabelText('Search tags')
        await act(async () => {
            fireEvent.change(input, { target: { value: 'rev' } })
        })
        expect(screen.getAllByRole('menuitemcheckbox').map((row) => row.textContent)).toEqual(['revenue'])

        await act(async () => {
            fireEvent.click(screen.getByText('revenue'))
        })

        expect(onChange).toHaveBeenCalledWith(['growth', 'revenue'])
        expect(screen.getByLabelText('Search tags')).toBeTruthy()
    })
})
