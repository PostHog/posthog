import { promoteMatchingBy } from 'lib/components/TaxonomicFilter/utils/promoteProperties'

describe('promoteMatchingBy', () => {
    const getName = (item: { name: string }): string => item.name
    const items = [{ name: '$browser' }, { name: '$pathname' }, { name: '$current_url' }, { name: '$email' }]

    it.each([
        ['url', '$current_url'],
        ['path', '$pathname'],
        ['email', '$email'],
        ['URL', '$current_url'],
        ['  path  ', '$pathname'],
    ])('floats the promoted property to position 0 when searching %p', (query, expectedFirst) => {
        const result = promoteMatchingBy(items, query, getName)
        expect(getName(result[0])).toBe(expectedFirst)
        expect(result).toHaveLength(items.length)
    })

    it.each([['browser'], [''], ['  '], ['random']])(
        'leaves order untouched when %p has no promoted property',
        (query) => {
            expect(promoteMatchingBy(items, query, getName)).toEqual(items)
        }
    )

    it('returns items unchanged when the promoted property is absent from the list', () => {
        const withoutUrl = [{ name: '$browser' }, { name: '$os' }]
        expect(promoteMatchingBy(withoutUrl, 'url', getName)).toEqual(withoutUrl)
    })
})
