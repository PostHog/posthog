import type { BreakPointFunction, ListenerFunction, Logic, LogicBuilder, LogicInput } from 'kea'

type ListenersBuilder = <L extends Logic = Logic>(input: LogicInput<L>['listeners']) => LogicBuilder<L>

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

function wrapListener(listener: ListenerFunction): ListenerFunction {
    return (payload, breakpoint, action, previousState) =>
        listener(payload, hasFakeTimers() ? breakpoint : fastBreakpoint(breakpoint), action, previousState)
}

export function testListenerDefinitions<L extends Logic = Logic>(
    input: LogicInput<L>['listeners']
): LogicInput<L>['listeners'] {
    return ((logic: L) => {
        const listeners = (typeof input === 'function' ? input(logic) : input) as Record<
            string,
            ListenerFunction | ListenerFunction[]
        >
        return Object.fromEntries(
            Object.entries(listeners).map(([action, listener]) => [
                action,
                Array.isArray(listener) ? listener.map((item) => wrapListener(item)) : wrapListener(listener),
            ])
        )
    }) as LogicInput<L>['listeners']
}

export function testListeners(listenersBuilder: ListenersBuilder): ListenersBuilder {
    return function listenersWithoutDelays<L extends Logic = Logic>(
        input: LogicInput<L>['listeners']
    ): LogicBuilder<L> {
        return listenersBuilder<L>(testListenerDefinitions(input))
    }
}
