import { getDOMMutationSignals } from './domMutationSignals'

describe('getDOMMutationSignals', () => {
    afterEach(() => {
        document.documentElement.className = ''
        document.body.innerHTML = ''
    })

    it.each([
        "NotFoundError: Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node.",
        "NotFoundError: Failed to execute 'insertBefore' on 'Node': The node before which the new node is to be inserted is not a child of this node.",
        "NotFoundError: Failed to execute 'appendChild' on 'Node': parameter 1 is not of type 'Node'.",
    ])('tags %s', (message) => {
        expect(getDOMMutationSignals(new Error(message)).dom_mutation_error).toBe(true)
    })

    it.each([new Error('Cannot read properties of undefined'), 'a string that is not a DOM error', null, undefined])(
        'leaves %p untagged',
        (error) => {
            expect(getDOMMutationSignals(error)).toEqual({})
        }
    )

    it('reports an untouched page as not translated', () => {
        const signals = getDOMMutationSignals(new Error("Failed to execute 'removeChild' on 'Node'"))

        expect(signals.page_translated).toBe(false)
        expect(signals.page_translation_hints).toBe('')
        expect(signals.injected_font_element_count).toBe(0)
    })

    it.each([
        ['Chrome wrapping translated text in <font>', () => (document.body.innerHTML = '<font>已翻译</font>')],
        ['the translated class on <html>', () => document.documentElement.classList.add('translated-ltr')],
        ['Microsoft translator attributes', () => (document.body.innerHTML = '<span _msttexthash="1">x</span>')],
    ])('reports the page as translated from %s', (_, applyFingerprint) => {
        applyFingerprint()

        const signals = getDOMMutationSignals(new Error("Failed to execute 'removeChild' on 'Node'"))

        expect(signals.page_translated).toBe(true)
        expect(signals.page_translation_hints).not.toBe('')
    })
})
