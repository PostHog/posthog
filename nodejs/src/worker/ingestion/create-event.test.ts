import { getElementsChain } from './create-event'

describe('getElementsChain', () => {
    it('returns empty string when neither $elements nor $elements_chain is present', () => {
        const properties = { foo: 'bar' }
        const result = getElementsChain(properties)
        expect(result).toBe('')
    })

    it('returns $elements_chain directly and removes it from properties', () => {
        const chain = 'div:nth-child="1"nth-of-type="2"'
        const properties = { $elements_chain: chain, other: 'value' }

        const result = getElementsChain(properties)

        expect(result).toBe(chain)
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).toHaveProperty('other', 'value')
    })

    it('converts $elements array to chain string and removes it from properties', () => {
        const properties = {
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
            other: 'value',
        }

        const result = getElementsChain(properties)

        expect(result).not.toBe('')
        expect(typeof result).toBe('string')
        expect(properties).not.toHaveProperty('$elements')
        expect(properties).toHaveProperty('other', 'value')
    })

    it('prefers $elements_chain over $elements when both are present, and removes both', () => {
        const chain = 'span:nth-child="3"nth-of-type="1"'
        const properties = {
            $elements_chain: chain,
            $elements: [{ tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: 'text' }],
        }

        const result = getElementsChain(properties)

        expect(result).toBe(chain)
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).not.toHaveProperty('$elements')
    })

    it('returns empty string and removes both keys when $elements is an empty array', () => {
        const properties = { $elements: [], $elements_chain: '' }

        const result = getElementsChain(properties)

        expect(result).toBe('')
        expect(properties).not.toHaveProperty('$elements_chain')
        expect(properties).not.toHaveProperty('$elements')
    })
})
