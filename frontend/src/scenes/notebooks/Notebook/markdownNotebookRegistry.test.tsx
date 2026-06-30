import { render } from '@testing-library/react'

import { NotebookNodeType } from '../types'
import { KNOWN_NODES } from '../utils'
import {
    NOTEBOOK_MARKDOWN_REGISTRY,
    RealNotebookNodeEdit,
    getEditableNodeAttributeKeys,
    getMarkdownNodeAttributeLabel,
    getQueryTitle,
    getSerializableAttributeInputValue,
    getSerializableProps,
} from './markdownNotebookRegistry'

describe('markdownNotebookRegistry', () => {
    it('does not make real notebook nodes mutually exclusive in markdown notebooks', () => {
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.Recording.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlag.exclusiveEditPanel).toBeUndefined()
        expect(NOTEBOOK_MARKDOWN_REGISTRY.components.FeatureFlagCodeExample.exclusiveEditPanel).toBeUndefined()
    })

    it('renders a lightweight feature flag reference editor instead of the full node view', () => {
        const { getByLabelText } = render(
            <RealNotebookNodeEdit
                node={{
                    id: 'feature-flag-node',
                    type: 'component',
                    tagName: 'FeatureFlag',
                    props: { id: 123 },
                }}
                mode="edit"
                updateProps={jest.fn()}
                deleteNode={jest.fn()}
            />
        )

        expect((getByLabelText('Feature flag ID or key') as HTMLInputElement).value).toEqual('123')
    })

    it('exposes lightweight editable primitive attrs for real notebook node filters', () => {
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.FeatureFlag], {
                id: 123,
            })
        ).toEqual(['id'])
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.Group], {
                groupTypeIndex: 0,
                id: 'org_123',
                placement: 'feed',
                tabId: 'properties',
            })
        ).toEqual(['id', 'groupTypeIndex'])
        expect(
            getEditableNodeAttributeKeys(KNOWN_NODES[NotebookNodeType.ZendeskTickets], {
                personId: undefined,
                groupKey: undefined,
            })
        ).toEqual(['personId', 'groupKey'])
    })

    it('uses product-specific labels for common reference attrs', () => {
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.FeatureFlag, 'id')).toEqual('Feature flag ID or key')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Group, 'groupTypeIndex')).toEqual('Group type index')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.Person, 'distinctId')).toEqual('Distinct ID')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.ZendeskTickets, 'personId')).toEqual('Person UUID')
        expect(getMarkdownNodeAttributeLabel(NotebookNodeType.ZendeskTickets, 'groupKey')).toEqual('Group key')
    })

    it('keeps numeric attrs numeric when edited through markdown filters', () => {
        expect(getSerializableAttributeInputValue(NotebookNodeType.Cohort, 'id', '123')).toEqual(123)
        expect(getSerializableAttributeInputValue(NotebookNodeType.Group, 'groupTypeIndex', '2')).toEqual(2)
        expect(getSerializableAttributeInputValue(NotebookNodeType.FeatureFlag, 'id', 'flag-key')).toEqual('flag-key')
        expect(getSerializableAttributeInputValue(NotebookNodeType.FeatureFlag, 'id', ' flag-key ')).toEqual('flag-key')
        expect(getSerializableAttributeInputValue(NotebookNodeType.Group, 'groupTypeIndex', ' not-a-number ')).toEqual(
            'not-a-number'
        )
    })

    describe('getQueryTitle', () => {
        it.each([
            [
                'ActorsQuery resolves to People, not the schema kind',
                { kind: 'DataTableNode', source: { kind: 'ActorsQuery' } },
                'People',
            ],
            ['EventsQuery resolves to Events', { kind: 'DataTableNode', source: { kind: 'EventsQuery' } }, 'Events'],
            [
                'HogQLQuery stays untitled — no SQL body, no generic label',
                { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select event from events' } },
                null,
            ],
            ['an unrecognized query suggests no title rather than the raw kind', { kind: 'DataTableNode' }, null],
        ])('%s', (_label, query, expected) => {
            expect(getQueryTitle(query)).toEqual(expected)
        })
    })

    describe('getSerializableProps', () => {
        it('preserves a query whose nested filter carries undefined fields, stripping the undefined', () => {
            // Regression: a completed person-property filter from the DataTable arrives with absent
            // label/group_type_index as `undefined`. Previously the whole `query` prop was dropped,
            // so the People table never re-queried when a filter was added.
            const result = getSerializableProps({
                query: {
                    kind: 'DataTableNode',
                    source: {
                        kind: 'ActorsQuery',
                        properties: [
                            { type: 'person', key: 'email', operator: 'exact', value: 'x@y.com', label: undefined },
                        ],
                    },
                },
            })

            expect(result.query).toEqual({
                kind: 'DataTableNode',
                source: {
                    kind: 'ActorsQuery',
                    properties: [{ type: 'person', key: 'email', operator: 'exact', value: 'x@y.com' }],
                },
            })
        })

        it('keeps a fully-serializable filter (e.g. cohort) untouched', () => {
            const query = {
                kind: 'DataTableNode',
                source: {
                    kind: 'ActorsQuery',
                    properties: [{ type: 'cohort', key: 'id', value: 42, operator: 'in' }],
                },
            }

            expect(getSerializableProps({ query }).query).toEqual(query)
        })

        it.each([
            ['undefined', { a: undefined }, {}],
            ['function', { a: () => undefined }, {}],
        ])('omits the key entirely when the value is not serializable (%s)', (_label, attributes, expected) => {
            expect(getSerializableProps(attributes as any)).toEqual(expected)
        })

        it('preserves primitive, array and nested object props', () => {
            expect(
                getSerializableProps({ id: 'abc', count: 3, enabled: true, items: ['a', 'b'], nested: { x: 1 } } as any)
            ).toEqual({ id: 'abc', count: 3, enabled: true, items: ['a', 'b'], nested: { x: 1 } })
        })

        it('strips undefined nested in an object while keeping its siblings', () => {
            expect(getSerializableProps({ nested: { keep: 'yes', drop: undefined } } as any)).toEqual({
                nested: { keep: 'yes' },
            })
        })
    })
})
