import type { BreakPointFunction, ListenerFunction, Logic, LogicBuilder, LogicInput } from 'kea'

type ListenersBuilder = <L extends Logic = Logic>(input: LogicInput<L>['listeners']) => LogicBuilder<L>

const REAL_BREAKPOINT_PATH_PREFIXES = [
    'products.workflows.frontend.Workflows.workflowLogic.',
    'scenes.max.maxThreadLogic.',
    'scenes.project-homepage.ai-first.aiFirstHomepageLogic',
    'scenes.session-recordings.player.sessionRecordingPlayerLogic.',
    'scenes.session-recordings.playlist.sessionRecordingsPlaylistLogic.',
    'scenes.session-recordings.snapshotLogic.',
]

function hasFakeTimers(): boolean {
    return 'clock' in setTimeout
}

function fastBreakpoint(breakpoint: BreakPointFunction): BreakPointFunction {
    return ((ms?: number): Promise<void> | void => {
        if (ms === undefined) {
            return breakpoint()
        }
        return breakpoint(0)
    }) as BreakPointFunction
}

function wrapListener(listener: ListenerFunction, keepDelay: boolean): ListenerFunction {
    return (payload, breakpoint, action, previousState) =>
        listener(payload, keepDelay || hasFakeTimers() ? breakpoint : fastBreakpoint(breakpoint), action, previousState)
}

export function testListeners(listenersBuilder: ListenersBuilder): ListenersBuilder {
    return function listenersWithoutDelays<L extends Logic = Logic>(
        input: LogicInput<L>['listeners']
    ): LogicBuilder<L> {
        return listenersBuilder<L>(((logic: L) => {
            const listeners = (typeof input === 'function' ? input(logic) : input) as Record<
                string,
                ListenerFunction | ListenerFunction[]
            >
            const keepDelay = REAL_BREAKPOINT_PATH_PREFIXES.some((prefix) => logic.pathString.startsWith(prefix))

            return Object.fromEntries(
                Object.entries(listeners).map(([action, listener]) => [
                    action,
                    Array.isArray(listener)
                        ? listener.map((item) => wrapListener(item, keepDelay))
                        : wrapListener(listener, keepDelay),
                ])
            )
        }) as LogicInput<L>['listeners'])
    }
}
