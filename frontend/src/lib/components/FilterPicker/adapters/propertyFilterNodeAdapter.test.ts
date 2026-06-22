import { PropertyFilterType, PropertyType } from '~/types'

import { FilterPickerNode } from '../FilterPicker.types'
import { CreatePropertyFilterNodesOptions, createPropertyFilterPickerNodes } from './propertyFilterNodeAdapter'

const baseOptions: Omit<CreatePropertyFilterNodesOptions, 'properties'> = {
    onSelect: () => {},
    valueLoader: () => ({ values: [{ value: 'a', label: 'Value A' }] }),
}

function childLabels(node: FilterPickerNode): string[] {
    const result = node.getChildren?.({ query: '', path: { nodeIds: [] } })
    return (result?.nodes ?? []).map((child) => String(child.label))
}

describe('createPropertyFilterPickerNodes', () => {
    it('auto-advances an auto category straight to the value step', () => {
        const [node] = createPropertyFilterPickerNodes({
            ...baseOptions,
            properties: [
                { key: 'id', label: 'Cohort', type: PropertyFilterType.Cohort, propertyType: PropertyType.Cohort },
            ],
        })

        // The property node renders values directly (no intermediate operator list).
        expect(childLabels(node)).toContain('Value A')
        expect(node.breadcrumbLabel).toBe('Cohort')
    })

    it('keeps the operator step for multi-operator categories', () => {
        const [node] = createPropertyFilterPickerNodes({
            ...baseOptions,
            properties: [
                { key: 'name', label: 'Name', type: PropertyFilterType.Event, propertyType: PropertyType.String },
            ],
        })

        // The property node renders operator choices, not values.
        const labels = childLabels(node)
        expect(labels.some((label) => label.includes('contains'))).toBe(true)
        expect(labels).not.toContain('Value A')
    })

    it('lets a property opt out of auto-advance with operatorMode pick', () => {
        const [node] = createPropertyFilterPickerNodes({
            ...baseOptions,
            properties: [
                {
                    key: 'id',
                    label: 'Cohort',
                    type: PropertyFilterType.Cohort,
                    propertyType: PropertyType.Cohort,
                    operatorMode: 'pick',
                },
            ],
        })

        expect(childLabels(node)).not.toContain('Value A')
    })
})
