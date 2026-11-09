const shutdownHandlers: (() => Promise<void>)[] = []

export const registerShutdownHandler = (handler: () => Promise<void>): void => {
    shutdownHandlers.push(handler)
}

export const onShutdown = async (): Promise<void> => {
    await Promise.allSettled(shutdownHandlers.map((handler) => handler()))
}
