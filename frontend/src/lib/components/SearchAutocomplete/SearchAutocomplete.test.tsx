import { fireEvent, render, screen } from '@testing-library/react'

import { SearchAutocomplete } from './SearchAutocomplete'

describe('SearchAutocomplete', () => {
    it('forwards keyboard events while suggestions are open', () => {
        const onKeyDown = jest.fn((event: React.KeyboardEvent<HTMLInputElement>) => event.preventDefault())
        render(
            <SearchAutocomplete
                searchData={[[{ label: 'status', value: 'status' }, [{ label: 'Failed', value: 'failed' }]]]}
                onKeyDown={onKeyDown}
            />
        )

        const input = screen.getByLabelText('Search input')
        fireEvent.change(input, { target: { value: 's' } })
        fireEvent.keyDown(input, { key: 'ArrowDown' })

        expect(onKeyDown).toHaveBeenCalledWith(expect.objectContaining({ key: 'ArrowDown' }))
    })
})
