import {
    createDetachedElementTrackingState,
    type DetachedElementRef,
    getDetachedElementTrackingContext,
    mapToTopN,
    measureDetachedPersistence,
    restartPersistenceSeries,
    shouldCaptureDetachedElements,
} from './detachedElementTracker'

describe('mapToTopN', () => {
    it.each([
        {
            label: 'empty map returns empty object',
            map: new Map<string, number>(),
            limit: 10,
            expected: {},
        },
        {
            label: 'fewer entries than limit returns all',
            map: new Map([
                ['div', 100],
                ['span', 50],
            ]),
            limit: 10,
            expected: { div: 100, span: 50 },
        },
        {
            label: 'more entries than limit returns top N by count',
            map: new Map([
                ['div', 100],
                ['span', 50],
                ['p', 200],
                ['a', 10],
            ]),
            limit: 2,
            expected: { p: 200, div: 100 },
        },
        {
            label: 'exactly limit entries returns all',
            map: new Map([
                ['div', 100],
                ['span', 50],
            ]),
            limit: 2,
            expected: { div: 100, span: 50 },
        },
        {
            label: 'ties are broken alphabetically',
            map: new Map([
                ['span', 100],
                ['div', 100],
                ['p', 100],
            ]),
            limit: 2,
            expected: { div: 100, p: 100 },
        },
        {
            label: 'limit of zero returns empty object',
            map: new Map([['div', 100]]),
            limit: 0,
            expected: {},
        },
    ])('$label', ({ map, limit, expected }) => {
        expect(mapToTopN(map, limit)).toEqual(expected)
    })
})

describe('shouldCaptureDetachedElements', () => {
    it.each([
        {
            label: 'skips when zero even on first scan',
            currentCount: 0,
            previousCount: null,
            persistedCount: 0,
            previousPersistedCount: null,
            expected: false,
        },
        {
            label: 'first scan with nonzero count always captures',
            currentCount: 5,
            previousCount: null,
            persistedCount: 0,
            previousPersistedCount: null,
            expected: true,
        },
        {
            label: 'skips when neither count changes',
            currentCount: 3,
            previousCount: 3,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: false,
        },
        {
            label: 'captures when count increases',
            currentCount: 5,
            previousCount: 3,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: true,
        },
        {
            label: 'captures when count decreases',
            currentCount: 2,
            previousCount: 5,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: true,
        },
        {
            label: 'skips when count stays at zero',
            currentCount: 0,
            previousCount: 0,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: false,
        },
        {
            label: 'captures when count goes from zero to nonzero',
            currentCount: 1,
            previousCount: 0,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: true,
        },
        {
            label: 'skips when count goes from nonzero to zero',
            currentCount: 0,
            previousCount: 7,
            persistedCount: 0,
            previousPersistedCount: 0,
            expected: false,
        },
        {
            label: 'captures when elements start surviving while the total holds still',
            currentCount: 100,
            previousCount: 100,
            persistedCount: 40,
            previousPersistedCount: 0,
            expected: true,
        },
        {
            label: 'captures when surviving elements are reclaimed while the total holds still',
            currentCount: 100,
            previousCount: 100,
            persistedCount: 0,
            previousPersistedCount: 40,
            expected: true,
        },
        {
            label: 'skips when the total and the persisted count both hold still',
            currentCount: 100,
            previousCount: 100,
            persistedCount: 40,
            previousPersistedCount: 40,
            expected: false,
        },
    ])('$label', ({ currentCount, previousCount, persistedCount, previousPersistedCount, expected }) => {
        expect(shouldCaptureDetachedElements(currentCount, previousCount, persistedCount, previousPersistedCount)).toBe(
            expected
        )
    })
})

describe('restartPersistenceSeries', () => {
    it('drops the persistence series and its baseline but keeps the route detached baseline', () => {
        const onRoute = getDetachedElementTrackingContext(createDetachedElementTrackingState(), 100, '/groups', 10)
        const growing = getDetachedElementTrackingContext(onRoute.nextState, 130, '/groups', 25)

        const resumed = restartPersistenceSeries(growing.nextState)
        const afterResume = getDetachedElementTrackingContext(resumed, 130, '/groups', 0)

        expect(afterResume.routeBaselinePersistedElements).toBe(0)
        expect(afterResume.routePersistedElementsDelta).toBe(0)
        expect(afterResume.routeBaselineDetachedElements).toBe(100)
        expect(afterResume.routeDetachedElementsDelta).toBe(30)
    })
})

describe('getDetachedElementTrackingContext', () => {
    it('resets the route baseline when the path changes', () => {
        const firstScan = getDetachedElementTrackingContext(createDetachedElementTrackingState(), 100, '/groups', 10)
        const sameRouteScan = getDetachedElementTrackingContext(firstScan.nextState, 130, '/groups', 25)
        const nextRouteScan = getDetachedElementTrackingContext(sameRouteScan.nextState, 50, '/pipeline/new/source', 20)
        const nextRouteGrowthScan = getDetachedElementTrackingContext(
            nextRouteScan.nextState,
            70,
            '/pipeline/new/source',
            22
        )

        expect(firstScan).toMatchObject({
            detachedElementsDelta: null,
            pathChanged: false,
            routeBaselineDetachedElements: 100,
            routeDetachedElementsDelta: 0,
            routeBaselinePersistedElements: 10,
            routePersistedElementsDelta: 0,
        })
        expect(sameRouteScan).toMatchObject({
            detachedElementsDelta: 30,
            routeBaselineDetachedElements: 100,
            routeDetachedElementsDelta: 30,
            routeBaselinePersistedElements: 10,
            routePersistedElementsDelta: 15,
        })
        expect(nextRouteScan).toMatchObject({
            detachedElementsDelta: -80,
            pathChanged: true,
            routeBaselineDetachedElements: 50,
            routeDetachedElementsDelta: 0,
            routeBaselinePersistedElements: 20,
            routePersistedElementsDelta: 0,
        })
        expect(nextRouteGrowthScan).toMatchObject({
            detachedElementsDelta: 20,
            pathChanged: false,
            routeBaselineDetachedElements: 50,
            routeDetachedElementsDelta: 20,
            routeBaselinePersistedElements: 20,
            routePersistedElementsDelta: 2,
        })
    })
})

describe('measureDetachedPersistence', () => {
    const ref = (element: Element | undefined, componentStack?: string[]): DetachedElementRef => ({
        element: { deref: () => element },
        componentStack,
    })

    it('counts only the elements that were already detached at the previous scan', () => {
        const survivor = document.createElement('div')
        const unnamedSurvivor = document.createElement('section')
        const freshlyDetached = document.createElement('span')

        const firstScan = measureDetachedPersistence(
            [ref(survivor, ['WorkflowsTable', 'WorkflowsScene']), ref(unnamedSurvivor)],
            new WeakSet()
        )
        const secondScan = measureDetachedPersistence(
            [
                ref(survivor, ['WorkflowsTable', 'WorkflowsScene']),
                ref(unnamedSurvivor),
                ref(freshlyDetached, ['LemonButton']),
            ],
            firstScan.seenNow
        )

        expect(firstScan.persistedCount).toBe(0)
        expect(secondScan.persistedCount).toBe(2)
        expect(Object.fromEntries(secondScan.persistedComponents)).toEqual({ WorkflowsTable: 1 })
    })

    it('ignores an element the collector has already taken', () => {
        const collected = ref(undefined, ['LemonButton'])
        const seenPreviously = new WeakSet<Element>()

        const scan = measureDetachedPersistence([collected], seenPreviously)

        expect(scan.persistedCount).toBe(0)
        expect(Object.fromEntries(scan.persistedComponents)).toEqual({})
    })
})
