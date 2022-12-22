import { ActionFilter } from '~/types'
import { actionsAndEventsToSeries } from './filtersToQueryNode'

describe('actionsAndEventsToSeries', () => {
    it('sorts series by order', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', order: 1, name: 'item2', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item3' },
        ]

        const result = actionsAndEventsToSeries({ actions, events })

        expect(result[0].name).toEqual('item1')
        expect(result[1].name).toEqual('item2')
        expect(result[2].name).toEqual('item3')
    })

    it('sorts elements without order first', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', name: 'itemWithOrder', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item2' },
        ]

        const result = actionsAndEventsToSeries({ actions, events })

        expect(result[0].name).toEqual('itemWithOrder')
        expect(result[1].name).toEqual('item1')
        expect(result[2].name).toEqual('item2')
    })
})
