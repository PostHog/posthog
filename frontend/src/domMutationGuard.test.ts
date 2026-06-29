import { patchDomMutationMethodsForExtensions } from './domMutationGuard'

describe('domMutationGuard', () => {
    beforeAll(() => {
        patchDomMutationMethodsForExtensions()
    })

    it('removeChild on a node that is no longer a child returns it instead of throwing', () => {
        // Simulates a browser extension having relocated the node out of `parent` before React's
        // commit phase calls removeChild — previously this threw NotFoundError and crashed reconciliation.
        const parent = document.createElement('div')
        const orphan = document.createElement('span')

        expect(() => parent.removeChild(orphan)).not.toThrow()
        expect(parent.removeChild(orphan)).toBe(orphan)
    })

    it('removeChild still removes a genuine child', () => {
        const parent = document.createElement('div')
        const child = document.createElement('span')
        parent.appendChild(child)

        expect(parent.removeChild(child)).toBe(child)
        expect(parent.contains(child)).toBe(false)
    })

    it('insertBefore with a reference node from a different parent returns the new node instead of throwing', () => {
        const parent = document.createElement('div')
        const otherParent = document.createElement('div')
        const reference = document.createElement('span')
        otherParent.appendChild(reference)
        const newNode = document.createElement('em')

        expect(() => parent.insertBefore(newNode, reference)).not.toThrow()
        expect(parent.insertBefore(newNode, reference)).toBe(newNode)
    })

    it('insertBefore still inserts before a valid reference node', () => {
        const parent = document.createElement('div')
        const reference = document.createElement('span')
        parent.appendChild(reference)
        const newNode = document.createElement('em')

        parent.insertBefore(newNode, reference)
        expect(parent.firstChild).toBe(newNode)
        expect(newNode.nextSibling).toBe(reference)
    })

    it('insertBefore with a null reference appends, as the spec requires', () => {
        const parent = document.createElement('div')
        const existing = document.createElement('span')
        parent.appendChild(existing)
        const newNode = document.createElement('em')

        parent.insertBefore(newNode, null)
        expect(parent.lastChild).toBe(newNode)
    })

    it('is idempotent — patching twice does not break normal mutation', () => {
        patchDomMutationMethodsForExtensions()
        const parent = document.createElement('div')
        const child = document.createElement('span')
        parent.appendChild(child)

        expect(parent.removeChild(child)).toBe(child)
        expect(parent.contains(child)).toBe(false)
    })
})
