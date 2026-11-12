// Fixed file name to content-hashed file name. Only the production build (frontend/build.mjs) defines it.
declare const __POSTHOG_WORKER_FILES__: Record<string, string> | undefined

/** The deploy overwrites a fixed-name file in place, so a tab open across deploys must load the worker of its own build. */
export function createWorker(fileName: string, options: WorkerOptions): Worker {
    const hashedName = typeof __POSTHOG_WORKER_FILES__ === 'undefined' ? undefined : __POSTHOG_WORKER_FILES__[fileName]
    return new Worker(`/static/${hashedName ?? fileName}`, options)
}
