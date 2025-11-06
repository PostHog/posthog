import { dayjs } from 'lib/dayjs'

import { TimeTree } from './time-tree'

type TestItem = { id: number; timestamp: dayjs.Dayjs }
describe('TimeTree', () => {
    const items = [
        { id: 0, timestamp: dayjs(10) },
        { id: 1, timestamp: dayjs(20) },
        { id: 2, timestamp: dayjs(30) },
        { id: 3, timestamp: dayjs(40) },
    ]

    it('can be created from timed items', () => {
        const tree = new TimeTree()
        tree.add(items)
    })

    it('can fetch previous item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const previous = tree.previous(dayjs(25))
        expect(previous).not.toBeUndefined()
        expect(previous!.id).toBe(1)
    })

    it('can fetch next item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const next = tree.next(dayjs(25))
        expect(next).not.toBeUndefined()
        expect(next!.id).toBe(2)
    })

    it('returns correct items on boundaries', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const prev = tree.previous(dayjs(30))
        const next = tree.next(dayjs(30))
        expect(prev!.id).toBe(1)
        expect(next!.id).toBe(3)
    })

    it('returns first item when before first item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const prev = tree.next(dayjs(5))
        expect(prev).not.toBeUndefined()
        expect(prev!.id).toBe(0)
    })

    it('returns last item when after last item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const prev = tree.previous(dayjs(50))
        expect(prev).not.toBeUndefined()
        expect(prev!.id).toBe(3)
    })

    it('returns null before first item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const prev = tree.previous(dayjs(5))
        expect(prev).toBeUndefined()
    })

    it('returns null after last item', () => {
        const tree = new TimeTree<TestItem>()
        tree.add(items)
        const next = tree.next(dayjs(45))
        expect(next).toBeUndefined()
    })
})
