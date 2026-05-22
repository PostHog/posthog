/**
 * Module-level switch for the self-read-only experiment.
 *
 * Lives outside any kea logic so it can be read from `lib/api.ts` without
 * pulling the layout/navigation logic into the lib graph. The kea logic
 * (`selfReadOnlyModeLogic`) registers a getter that reads its current state.
 */

export class ReadOnlyModeError extends Error {
    // Many call sites in the app catch api errors with the shape
    // `lemonToast.error(error.detail || 'Failed to ...')`. Without `detail`,
    // a read-only block would surface as the misleading fallback ("Failed to
    // launch experiment" etc.) on top of the dedicated read-only toast.
    // Setting `detail` here keeps that secondary toast at least truthful.
    detail = 'Read-only mode is on — change blocked. Use Max or the MCP to make this change.'

    constructor(message = 'You are in read-only mode') {
        super(message)
        this.name = 'ReadOnlyModeError'
    }
}

type Notifier = (method: 'PATCH' | 'PUT' | 'POST' | 'DELETE') => void
type Getter = () => boolean

let getter: Getter | null = null
let notifier: Notifier | null = null

export function setReadOnlyGetter(fn: Getter | null): void {
    if (fn && getter) {
        // eslint-disable-next-line no-console
        console.warn(
            '[readOnlyGuard] setReadOnlyGetter called while a getter is already registered — overwriting. This usually means selfReadOnlyModeLogic was mounted twice.'
        )
    }
    getter = fn
}

export function setReadOnlyNotifier(fn: Notifier | null): void {
    notifier = fn
}

export function isReadOnly(): boolean {
    return getter?.() ?? false
}

export function assertNotReadOnly(method: 'PATCH' | 'PUT' | 'POST' | 'DELETE'): void {
    if (!isReadOnly()) {
        return
    }
    notifier?.(method)
    throw new ReadOnlyModeError()
}
