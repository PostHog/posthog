export interface Breakpoint<T = void> {
    wait: Promise<T>
    complete: (value: T) => void
}

export function createBreakpoint<T = void>(): Breakpoint<T> {
    let complete!: (value: T) => void
    const wait = new Promise<T>((resolve) => {
        complete = resolve
    })
    return { wait, complete }
}

export class SequenceExecutor {
    private breakpoints: Array<Promise<unknown>> = []

    add<T>(breakpoint: Breakpoint<T>): void {
        this.breakpoints.push(breakpoint.wait)
    }

    async run(): Promise<void> {
        for (const wait of this.breakpoints) {
            await wait
        }
    }
}

export function createTestSequence(waits: Array<Promise<unknown>>): SequenceExecutor {
    const executor = new SequenceExecutor()
    for (const wait of waits) {
        executor.add({ wait, complete: () => {} })
    }
    return executor
}
