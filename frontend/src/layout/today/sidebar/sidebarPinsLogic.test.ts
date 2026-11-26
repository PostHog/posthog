import { FileSystemEntry } from '~/queries/schema/schema-general'

import { fileSystemPinTarget } from './sidebarPinsLogic'

const entry = (overrides: Partial<FileSystemEntry>): FileSystemEntry =>
    ({
        id: 'row',
        path: 'Unfiled/Insights/Signups',
        type: 'insight/trends',
        ref: 'abc',
        href: '/insights/abc',
        ...overrides,
    }) as FileSystemEntry

describe('fileSystemPinTarget', () => {
    test.each([
        [
            'a subtype pins as its base type',
            entry({}),
            { type: 'insight', ref: 'abc', name: 'Signups', href: '/insights/abc' },
        ],
        [
            'an escaped slash stays in the name',
            entry({ path: 'Unfiled/Insights/A\\/B test' }),
            { type: 'insight', ref: 'abc', name: 'A/B test', href: '/insights/abc' },
        ],
        ['a row with no ref pins nothing', entry({ ref: undefined }), null],
        ['no row pins nothing', null, null],
    ])('%s', (_, row, expected) => {
        expect(fileSystemPinTarget(row)).toEqual(expected)
    })
})
