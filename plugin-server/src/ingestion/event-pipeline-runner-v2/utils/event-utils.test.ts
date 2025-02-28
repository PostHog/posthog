import { elementsToString, extractElements, normalizeEvent } from './event-utils'

describe('elementsToString and chainToElements', () => {
    it('handles element containing quotes and colons', () => {
        const element = {
            tag_name: 'a',
            href: '/a-url',
            attr_class: ['small"', 'xy:z'],
            attributes: {
                attr_class: 'xyz small"',
            },
        }

        const elementsString = elementsToString([element])

        expect(elementsString).toEqual(
            'a.small.xy:z:attr_class="xyz small\\""href="/a-url"nth-child="0"nth-of-type="0"'
        )
    })

    it('handles multiple classNames', () => {
        const element = {
            attr_class: ['something', 'another'],
            attributes: {
                attr__class: 'something another',
            },
        }
        const elementsString = elementsToString([element])

        expect(elementsString).toEqual('.another.something:attr__class="something another"nth-child="0"nth-of-type="0"')
    })
})

describe('extractElements()', () => {
    it('parses simple elements', () => {
        const result = extractElements([
            { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
            { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
        ])

        expect(result).toEqual([
            {
                text: undefined,
                tag_name: 'a',
                href: undefined,
                attr_class: ['btn', 'btn-sm'],
                attr_id: undefined,
                nth_child: 1,
                nth_of_type: 2,
                attributes: { attr__class: 'btn btn-sm' },
            },
            {
                text: '💻',
                tag_name: 'div',
                href: undefined,
                attr_class: undefined,
                attr_id: undefined,
                nth_child: 1,
                nth_of_type: 2,
                attributes: {},
            },
        ])
    })

    it('handles arrays for attr__class', () => {
        const result = extractElements([{ attr__class: ['btn', 'btn-sm'] }])

        expect(result[0]).toEqual(
            expect.objectContaining({
                attr_class: ['btn', 'btn-sm'],
                attributes: { attr__class: ['btn', 'btn-sm'] },
            })
        )
    })
})

describe('normalizeEvent()', () => {
    describe('distinctId', () => {
        test.each([
            { distinctId: 'abc', expected: 'abc' },
            { distinctId: 123, expected: '123' },
            { distinctId: true, expected: 'true' },
        ])('$distinctId', ({ distinctId, expected }) => {
            const event = { distinct_id: distinctId }
            expect(normalizeEvent(event as any).distinct_id).toBe(expected)
        })
    })

    it('adds missing properties', () => {
        const event = { distinct_id: 'something' }
        expect(normalizeEvent(event as any).properties).toEqual({})

        const event2 = { distinct_id: 'something', properties: { a: 1 }, sent_at: '2020-02-23T02:15:00.000Z' }
        expect(normalizeEvent(event2 as any).properties).toEqual({ a: 1, $sent_at: '2020-02-23T02:15:00.000Z' })
    })

    it('combines .properties $set and $set_once with top-level $set and $set_once', () => {
        const event = {
            event: 'some_event',
            $set: { key1: 'value1', key2: 'value2' },
            $set_once: { key1_once: 'value1', key2_once: 'value2' },
            properties: {
                distinct_id: 'distinct_id1',
                $set: { key2: 'value3', key3: 'value4' },
                $set_once: { key2_once: 'value3', key3_once: 'value4' },
            },
        }
        const sanitized = normalizeEvent(event as any)

        expect(sanitized.properties!['$set']).toEqual({ key1: 'value1', key2: 'value2', key3: 'value4' })
        expect(sanitized.properties!['$set_once']).toEqual({
            key1_once: 'value1',
            key2_once: 'value2',
            key3_once: 'value4',
        })
    })
})
