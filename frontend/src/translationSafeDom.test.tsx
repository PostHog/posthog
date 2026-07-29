import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { installTranslationSafeDom } from './translationSafeDom'

/** What every in-page translator does: swap each bare text node for a `<font>` wrapper. */
function translate(root: HTMLElement): void {
    const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    const texts: Text[] = []
    while (walker.nextNode()) {
        texts.push(walker.currentNode as Text)
    }
    for (const text of texts) {
        const font = root.ownerDocument.createElement('font')
        font.textContent = `[${text.textContent}]`
        text.parentNode?.replaceChild(font, text)
    }
}

function Conditional({ showFirst }: { showFirst: boolean }): JSX.Element {
    return (
        <div>
            {showFirst ? 'first' : null}
            <span>second</span>
        </div>
    )
}

describe('installTranslationSafeDom', () => {
    let restore: () => void
    let posthog: { capture: jest.Mock }

    beforeEach(() => {
        posthog = { capture: jest.fn() }
        restore = installTranslationSafeDom(posthog)
    })

    afterEach(() => {
        cleanup()
        restore()
    })

    it('lets React re-render a subtree whose text nodes were replaced by translation', () => {
        const { container, rerender } = render(<Conditional showFirst />)

        translate(container)

        expect(() => rerender(<Conditional showFirst={false} />)).not.toThrow()
        expect(posthog.capture).toHaveBeenCalledWith('translation_safe_dom_guarded', expect.anything())
    })

    it('reports only the first guarded mutation per page load', () => {
        const { container, rerender } = render(<Conditional showFirst />)
        translate(container)

        rerender(<Conditional showFirst={false} />)
        rerender(<Conditional showFirst />)
        translate(container)
        rerender(<Conditional showFirst={false} />)

        expect(posthog.capture).toHaveBeenCalledTimes(1)
    })

    it('still removes a node that is a child', () => {
        const parent = document.createElement('div')
        const child = document.createElement('span')
        parent.appendChild(child)

        expect(parent.removeChild(child)).toBe(child)
        expect(parent.childNodes).toHaveLength(0)
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('still inserts before a reference node that is a child', () => {
        const parent = document.createElement('div')
        const reference = document.createElement('span')
        const inserted = document.createElement('b')
        parent.appendChild(reference)

        parent.insertBefore(inserted, reference)

        expect(Array.from(parent.childNodes)).toEqual([inserted, reference])
        expect(posthog.capture).not.toHaveBeenCalled()
    })

    it('appends instead of throwing when the reference node belongs to another parent', () => {
        const parent = document.createElement('div')
        const existing = document.createElement('span')
        parent.appendChild(existing)
        const foreignReference = document.createElement('em')
        document.createElement('div').appendChild(foreignReference)
        const inserted = document.createElement('b')

        parent.insertBefore(inserted, foreignReference)

        expect(Array.from(parent.childNodes)).toEqual([existing, inserted])
        expect(posthog.capture).toHaveBeenCalledTimes(1)
    })

    it('restores the native mutators so a missing child throws again', () => {
        restore()
        restore = () => {}

        const parent = document.createElement('div')
        expect(() => parent.removeChild(document.createElement('span'))).toThrow()
    })
})
