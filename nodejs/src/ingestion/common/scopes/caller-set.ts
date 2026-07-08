// Refcount with single-shot release callbacks.

export class CallerSet {
    private callers = new Set<number>()
    private nextId = 0

    register(): () => boolean {
        const id = this.nextId++
        this.callers.add(id)
        let released = false
        return () => {
            if (released) {
                return false
            }
            released = true
            this.callers.delete(id)
            return true
        }
    }

    size(): number {
        return this.callers.size
    }
}
