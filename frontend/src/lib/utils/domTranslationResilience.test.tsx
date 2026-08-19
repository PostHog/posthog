import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { installDOMTranslationResilience } from './domTranslationResilience'

// A conditional bare-text child next to an element — the shape a single-select value prefix
// produces (label text alongside the input). Toggling the label makes React remove the text node.
function Field({ showLabel }: { showLabel: boolean }): JSX.Element {
    return (
        <div id="host">
            {showLabel ? 'https://example.com/pricing' : null}
            <span>input</span>
        </div>
    )
}

// Reproduces what a page-translation extension does to `Field`: wrap the label text node in a
// <font>, reparenting it out of #host, then re-render so React must remove that stale node.
async function renderThenReparentThenUpdate(): Promise<Error | null> {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
        root.render(<Field showLabel={true} />)
    })

    const host = container.querySelector('#host') as HTMLElement
    const textNode = host.firstChild as Text
    const font = document.createElement('font')
    host.insertBefore(font, textNode)
    font.appendChild(textNode)

    let caught: Error | null = null
    try {
        await act(async () => {
            root.render(<Field showLabel={false} />)
        })
    } catch (error) {
        caught = error as Error
    }
    root.unmount()
    container.remove()
    return caught
}

describe('domTranslationResilience', () => {
    // Runs before install, so it captures the native throwing behaviour.
    it('React crashes on a translator reparent without the patch', async () => {
        const error = await renderThenReparentThenUpdate()
        expect(error?.message).toContain('not a child of this node')
    })

    it('React survives the same translator reparent once the patch is installed', async () => {
        installDOMTranslationResilience()
        const error = await renderThenReparentThenUpdate()
        expect(error).toBeNull()
    })

    it('keeps a reparented reference node in the tree instead of throwing', () => {
        installDOMTranslationResilience()
        const parent = document.createElement('div')
        const reference = document.createElement('span')
        document.createElement('div').appendChild(reference) // reference lives elsewhere

        const inserted = document.createElement('b')
        expect(() => parent.insertBefore(inserted, reference)).not.toThrow()
        expect(inserted.parentNode).toBe(parent)
    })

    it('treats removing an already-detached child as a no-op', () => {
        installDOMTranslationResilience()
        const parent = document.createElement('div')
        const detached = document.createElement('span')
        expect(parent.removeChild(detached)).toBe(detached)
    })

    it('leaves correct insertBefore and removeChild behaviour unchanged', () => {
        installDOMTranslationResilience()
        const parent = document.createElement('div')
        const reference = document.createElement('span')
        parent.appendChild(reference)

        const inserted = document.createElement('b')
        parent.insertBefore(inserted, reference)
        expect(Array.from(parent.childNodes)).toEqual([inserted, reference])

        parent.removeChild(inserted)
        expect(Array.from(parent.childNodes)).toEqual([reference])
    })
})
