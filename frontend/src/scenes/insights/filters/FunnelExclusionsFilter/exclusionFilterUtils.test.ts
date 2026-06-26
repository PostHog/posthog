import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes, FilterType } from '~/types'

import { exclusionFiltersToNodes } from './exclusionFilterUtils'

describe('exclusionFiltersToNodes', () => {
    it('includes action-based exclusions, not just events', () => {
        const filters: Partial<FilterType> = {
            events: [{ id: '$pageview', type: EntityTypes.EVENTS, order: 0, funnel_from_step: 0, funnel_to_step: 1 }],
            actions: [{ id: 3, type: EntityTypes.ACTIONS, order: 1, funnel_from_step: 0, funnel_to_step: 2 }],
        }

        const result = exclusionFiltersToNodes(filters)

        expect(result).toHaveLength(2)
        expect(result[1]).toMatchObject({ kind: NodeKind.ActionsNode, id: 3, funnelFromStep: 0, funnelToStep: 2 })
    })

    it('preserves property filters configured on an exclusion', () => {
        const filters: Partial<FilterType> = {
            events: [
                {
                    id: '$pageview',
                    type: EntityTypes.EVENTS,
                    order: 0,
                    funnel_from_step: 0,
                    funnel_to_step: 1,
                    properties: [{ key: '$browser', value: 'Chrome', operator: 'exact', type: 'event' }],
                },
            ],
        }

        const result = exclusionFiltersToNodes(filters)

        expect(result[0]).toMatchObject({ kind: NodeKind.EventsNode, event: '$pageview' })
        expect(result[0].properties).toMatchObject([{ key: '$browser', value: 'Chrome' }])
    })

    it('orders interleaved event and action exclusions by their row order', () => {
        const filters: Partial<FilterType> = {
            events: [
                { id: 'first', type: EntityTypes.EVENTS, order: 0, funnel_from_step: 0, funnel_to_step: 1 },
                { id: 'third', type: EntityTypes.EVENTS, order: 2, funnel_from_step: 0, funnel_to_step: 1 },
            ],
            actions: [{ id: 2, type: EntityTypes.ACTIONS, order: 1, funnel_from_step: 0, funnel_to_step: 1 }],
        }

        const result = exclusionFiltersToNodes(filters)

        expect(result.map((node) => (node.kind === NodeKind.EventsNode ? node.event : node.id))).toEqual([
            'first',
            2,
            'third',
        ])
    })
})
