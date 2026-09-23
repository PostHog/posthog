import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { FolderNavigation } from './FolderNavigation'
import { joinPath } from './utils'

describe('FolderNavigation', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('goes up and jumps to an ancestor without splitting escaped folder names', async () => {
        const onOpen = jest.fn()
        const parent = joinPath(['Research/Design', 'Notes \\ drafts'])
        render(<FolderNavigation folder={joinPath(['Research/Design', 'Notes \\ drafts', 'Ideas'])} onOpen={onOpen} />)
        fireEvent.click(screen.getByLabelText('Parent folder'))
        expect(onOpen).toHaveBeenLastCalledWith(parent)
        fireEvent.click(screen.getByLabelText('Choose folder level'))
        fireEvent.click(await screen.findByText('Research/Design'))
        expect(onOpen).toHaveBeenLastCalledWith(joinPath(['Research/Design']))
        fireEvent.click(screen.getByLabelText('Choose folder level'))
        fireEvent.click(await screen.findByText('Files'))
        expect(onOpen).toHaveBeenLastCalledWith('')
    })
})
