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

    it('floats exact key matches above substring-only matches', () => {
        const idItems = [{ name: 'organization_id' }, { name: 'device_id' }, { name: 'id' }, { name: 'team_id' }]
        const result = promoteMatchingBy(idItems, 'id', getName)
        expect(getName(result[0])).toBe('id')
        expect(result).toHaveLength(idItems.length)
    })

    it('keeps mapped promotions ahead of exact key matches', () => {
        const mixed = [{ name: 'url' }, { name: '$current_url' }]
        const result = promoteMatchingBy(mixed, 'url', getName)
        expect(result.map(getName)).toEqual(['$current_url', 'url'])
    })

    it('returns items unchanged when the promoted property is absent from the list', () => {
        const withoutUrl = [{ name: '$browser' }, { name: '$os' }]
        expect(promoteMatchingBy(withoutUrl, 'url', getName)).toEqual(withoutUrl)
    })
})
