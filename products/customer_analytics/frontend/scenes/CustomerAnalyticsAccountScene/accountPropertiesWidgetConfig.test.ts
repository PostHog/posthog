import {
    accountWidgetKeysToReferences,
    getAccountWidgetProperties,
    getAccountWidgetPropertyKey,
} from './accountPropertiesWidgetConfig'
import { createAccountViewContent, parseAccountViewContent } from './accountViewDocument'

const CUSTOM_ID = '11111111-1111-4111-8111-111111111111'
const RELATIONSHIP_ID = '22222222-2222-4222-8222-222222222222'

const first = [
    { kind: 'account', key: 'website_domain' },
    { kind: 'custom_property', id: CUSTOM_ID },
]
const second = [
    { kind: 'relationship', id: RELATIONSHIP_ID },
    { kind: 'account', key: 'known_emails' },
    { kind: 'custom_property', id: CUSTOM_ID },
]

describe('account properties widget config', () => {
    it('round-trips independent mixed selections in order, including stale definition IDs', () => {
        const components = parseAccountViewContent(
            createAccountViewContent([
                { nodeId: 'first', kind: 'properties', span: 6, config: { properties: first } },
                { nodeId: 'notes', kind: 'notes', span: 12, config: { searchTerm: 'Note search' } },
                { nodeId: 'second', kind: 'properties', span: 6, config: { properties: second } },
            ])
        )
        expect(components.map(({ nodeId }) => nodeId)).toEqual(['first', 'notes', 'second'])
        expect(getAccountWidgetProperties(components[0].config)).toEqual(first)
        expect(getAccountWidgetProperties(components[2].config)).toEqual(second)
        expect(components[1].config).toEqual({ searchTerm: 'Note search' })
        expect(
            accountWidgetKeysToReferences(
                getAccountWidgetProperties(components[2].config).map(getAccountWidgetPropertyKey)
            )
        ).toEqual(second)
    })

    it.each([undefined, { properties: null }, { properties: 'website_domain' }])(
        'reads missing or malformed config as an empty selection (%s)',
        (config) => {
            expect(getAccountWidgetProperties(config)).toEqual([])
        }
    )

    it('resolves UUID case consistently and treats equivalent spellings as one reference', () => {
        const id = 'abcdefab-cdef-4abc-8def-abcdefabcdef'
        expect(
            getAccountWidgetProperties({
                properties: [
                    { kind: 'custom_property', id: id.toUpperCase() },
                    { kind: 'custom_property', id },
                ],
            })
        ).toEqual([{ kind: 'custom_property', id }])
    })

    it('omits unknown sources, arbitrary account keys and malformed IDs without replacing valid references', () => {
        expect(
            getAccountWidgetProperties({
                properties: [
                    { kind: 'account', key: 'name' },
                    { kind: 'account', key: 'arbitrary_key' },
                    { kind: 'custom_property', id: 'invalid' },
                    { kind: 'unknown', id: CUSTOM_ID },
                    null,
                    ...first,
                    ...first,
                ],
            })
        ).toEqual(first)
    })
})
