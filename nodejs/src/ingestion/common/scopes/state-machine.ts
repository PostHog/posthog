// Drives a scope through its stopped → starting → started → stopping
// lifecycle, sharing in-flight start/stop work and serializing transitions.

export interface ScopeContext {
    runStart(): Promise<void>
    runStop(): Promise<void>
    callerCount(): number
}

type Outcome =
    | { kind: 'transition'; next: ScopeState }
    | { kind: 'wait'; on: Promise<unknown> }
    | { kind: 'done' }
    | { kind: 'failed'; next: ScopeState; error: unknown }

interface ScopeState {
    onStart(ctx: ScopeContext): Outcome
    onStop(ctx: ScopeContext): Outcome
}

class StoppedState implements ScopeState {
    onStart(ctx: ScopeContext): Outcome {
        return { kind: 'transition', next: new StartingState(ctx.runStart()) }
    }
    onStop(_ctx: ScopeContext): Outcome {
        return { kind: 'done' }
    }
}

class StartingState implements ScopeState {
    private settled: 'pending' | 'ok' | { error: unknown } = 'pending'
    private readonly waitOn: Promise<void>

    constructor(startPromise: Promise<void>) {
        this.waitOn = startPromise.then(
            () => {
                this.settled = 'ok'
            },
            (err: unknown) => {
                this.settled = { error: err }
            }
        )
    }

    onStart(_ctx: ScopeContext): Outcome {
        return this.snapshot()
    }
    onStop(_ctx: ScopeContext): Outcome {
        return this.snapshot()
    }

    private snapshot(): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        if (this.settled === 'ok') {
            return { kind: 'transition', next: new StartedState() }
        }
        return { kind: 'failed', next: new StoppedState(), error: this.settled.error }
    }
}

class StartedState implements ScopeState {
    onStart(_ctx: ScopeContext): Outcome {
        return { kind: 'done' }
    }
    onStop(ctx: ScopeContext): Outcome {
        if (ctx.callerCount() === 0) {
            return { kind: 'transition', next: new StoppingState(ctx.runStop()) }
        }
        return { kind: 'done' }
    }
}

class StoppingState implements ScopeState {
    private settled: 'pending' | 'ok' | { error: unknown } = 'pending'
    private readonly waitOn: Promise<void>

    constructor(stopPromise: Promise<void>) {
        this.waitOn = stopPromise.then(
            () => {
                this.settled = 'ok'
            },
            (err: unknown) => {
                this.settled = { error: err }
            }
        )
    }

    onStart(_ctx: ScopeContext): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        return { kind: 'transition', next: new StoppedState() }
    }

    onStop(_ctx: ScopeContext): Outcome {
        if (this.settled === 'pending') {
            return { kind: 'wait', on: this.waitOn }
        }
        if (this.settled === 'ok') {
            return { kind: 'transition', next: new StoppedState() }
        }
        return { kind: 'failed', next: new StoppedState(), error: this.settled.error }
    }
}

export class StateMachine {
    private state: ScopeState = new StoppedState()

    async start(ctx: ScopeContext): Promise<void> {
        await this.drive((s) => s.onStart(ctx))
    }

    async stop(ctx: ScopeContext): Promise<void> {
        await this.drive((s) => s.onStop(ctx))
    }

    private async drive(action: (state: ScopeState) => Outcome): Promise<void> {
        while (true) {
            const outcome = action(this.state)
            if (outcome.kind === 'transition') {
                this.state = outcome.next
                continue
            }
            if (outcome.kind === 'wait') {
                await outcome.on
                continue
            }
            if (outcome.kind === 'failed') {
                this.state = outcome.next
                throw outcome.error
            }
            return
        }
    }
}
