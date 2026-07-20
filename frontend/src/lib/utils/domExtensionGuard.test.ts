import { installDOMExtensionGuard } from './domExtensionGuard'

describe('domExtensionGuard', () => {
    beforeAll(() => {
        installDOMExtensionGuard()
    })

    it('no-ops removeChild when the node was moved out from under its expected parent', () => {
        const parent = document.createElement('div')
        const orphan = document.createElement('span')
        // orphan was never appended to parent — mimics an extension detaching the node

        expect(() => parent.removeChild(orphan)).not.toThrow()
        expect(parent.removeChild(orphan)).toBe(orphan)
    })

    it('still removes a genuine child', () => {
        const parent = document.createElement('div')
        const child = document.createElement('span')
        parent.appendChild(child)

        expect(parent.removeChild(child)).toBe(child)
        expect(parent.contains(child)).toBe(false)
    })

    it('falls back to appending on insertBefore when the reference node has a different parent', () => {
        const parent = document.createElement('div')
        const newNode = document.createElement('span')
        const strayReference = document.createElement('em') // not a child of parent

        expect(() => parent.insertBefore(newNode, strayReference)).not.toThrow()
        expect(parent.lastChild).toBe(newNode)
    })

    it('still inserts before a genuine reference child', () => {
        const parent = document.createElement('div')
        const existing = document.createElement('span')
        const newNode = document.createElement('em')
        parent.appendChild(existing)

        parent.insertBefore(newNode, existing)
        expect(parent.firstChild).toBe(newNode)
    })
})
