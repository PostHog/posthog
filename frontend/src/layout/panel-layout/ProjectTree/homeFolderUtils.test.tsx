import { render, screen, cleanup } from '@testing-library/react'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

import { isHomeFolder, withHomeFolderEmptyState } from './homeFolderUtils'

describe('home folder tree presentation', () => {
    afterEach(cleanup)

    it.each([
        ['project://Users/Alex', 'home', 'Users/Alex', undefined, true],
        ['shortcuts://Alex', 'star', 'Alex', 'Users/Alex', true],
        ['project://Research/My work', 'home', 'Research/My work', undefined, true],
        ['project://Users/Alex (1)', 'other', 'Users/Alex (1)', undefined, false],
        ['shortcuts://Alex (1)', 'star-other', 'Alex (1)', 'Users/Alex (1)', false],
    ])('identifies %s and only gives the owner home-folder guidance', (id, recordId, path, ref, own) => {
        const home = { id: 'home', path: 'Users/Alex' }
        const item: TreeDataItem = {
            id,
            name: path,
            record: { id: recordId, path, ref, type: 'folder' },
            children: [{ id: 'empty', name: 'Empty folder', type: 'empty-folder', displayName: <>Empty folder</> }],
        }
        expect(isHomeFolder(item, home)).toBe(own)
        const [result] = withHomeFolderEmptyState([item], home)
        render(<>{result.children?.[0].displayName}</>)
        expect(!!screen.queryByText('Empty home folder')).toBe(own)
        expect(item.children?.[0].name).toBe('Empty folder')
    })
})
