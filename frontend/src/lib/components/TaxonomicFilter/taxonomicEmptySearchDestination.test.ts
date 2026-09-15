import {
    EMPTY_SEARCH_RETURN_WINDOW_MS,
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
            'explore',
        ],
        [
            'person context',
            group({ name: 'Person properties', type: TaxonomicFilterGroupType.PersonProperties }),
            [],
            '/persons',
            '',
            'persons',
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
            'groups',
        ],
    ])(
        'routes %s to the relevant page with the available context',
        (_, taxonomicGroup, eventNames, path, query, expectedDestination) => {
            const destination = taxonomicEmptySearchDestination(taxonomicGroup, eventNames)

            expect(destination?.url).toContain(path)
            expect(decodeURIComponent(destination?.url ?? '')).toContain(query)
            expect(destination?.destination).toBe(expectedDestination)
        }
    )

    it('marks the next selection only after the original tab regains focus', () => {
        const onReturn = jest.fn()
        markEmptySearchDestinationOpened(onReturn)

        expect(consumeEmptySearchDestinationReturn()).toBe(false)

        window.dispatchEvent(new Event('focus'))

        expect(onReturn).toHaveBeenCalledTimes(1)
        expect(consumeEmptySearchDestinationReturn()).toBe(true)
        expect(consumeEmptySearchDestinationReturn()).toBe(false)
    })

    it('removes the pending listener when marking a new one', () => {
        const onReturn1 = jest.fn()
        const onReturn2 = jest.fn()
        markEmptySearchDestinationOpened(onReturn1)
        markEmptySearchDestinationOpened(onReturn2)

        window.dispatchEvent(new Event('focus'))

        expect(onReturn1).not.toHaveBeenCalled()
        expect(onReturn2).toHaveBeenCalledTimes(1)
        expect(consumeEmptySearchDestinationReturn()).toBe(true)
    })

    it('forgets a return once the funnel window has passed', () => {
        jest.useFakeTimers()
        try {
            jest.setSystemTime(0)
            markEmptySearchDestinationOpened(jest.fn())
            window.dispatchEvent(new Event('focus'))

            jest.setSystemTime(EMPTY_SEARCH_RETURN_WINDOW_MS)

            expect(consumeEmptySearchDestinationReturn()).toBe(false)
        } finally {
            jest.useRealTimers()
        }
    })
})
