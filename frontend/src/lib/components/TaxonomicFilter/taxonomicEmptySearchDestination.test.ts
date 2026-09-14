import {
    consumeEmptySearchDestinationReturn,
    markEmptySearchDestinationOpened,
    taxonomicEmptySearchDestination,
} from './taxonomicEmptySearchDestination'
import { TaxonomicFilterGroupType } from './types'
import type { TaxonomicFilterGroup } from './types'

describe('taxonomicEmptySearchDestination', () => {
    const group = (overrides: Partial<TaxonomicFilterGroup>): TaxonomicFilterGroup =>
        ({
            name: 'Events',
            searchPlaceholder: 'events',
            type: TaxonomicFilterGroupType.Events,
            getPopoverHeader: () => 'Events',
            ...overrides,
        }) as TaxonomicFilterGroup

    test.each([
        [
            'event context',
            group({ type: TaxonomicFilterGroupType.EventProperties }),
            ['$pageview'],
            '/activity/explore',
            '"event":"$pageview"',
        ],
        [
            'person context',
            group({ name: 'Person properties', type: TaxonomicFilterGroupType.PersonProperties }),
            [],
            '/persons',
            '',
        ],
        [
            'group context',
            group({
                name: 'Organizations',
                type: `${TaxonomicFilterGroupType.GroupsPrefix}_0` as TaxonomicFilterGroupType,
                groupTypeIndex: 0,
            }),
            [],
            '/groups/0',
            '',
        ],
    ])('routes %s to the relevant page with the available context', (_, taxonomicGroup, eventNames, path, query) => {
        const destination = taxonomicEmptySearchDestination(taxonomicGroup, eventNames)

        expect(destination?.url).toContain(path)
        expect(decodeURIComponent(destination?.url ?? '')).toContain(query)
    })

    it('marks the next selection only after the original tab regains focus', () => {
        const onReturn = jest.fn()
        markEmptySearchDestinationOpened(onReturn)

        expect(consumeEmptySearchDestinationReturn()).toBe(false)

        window.dispatchEvent(new Event('focus'))

        expect(onReturn).toHaveBeenCalledTimes(1)
        expect(consumeEmptySearchDestinationReturn()).toBe(true)
        expect(consumeEmptySearchDestinationReturn()).toBe(false)
    })
})
