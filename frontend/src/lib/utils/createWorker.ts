// Fixed file name to content-hashed file name. Only the production build (frontend/build.mjs) defines it.
declare const __POSTHOG_WORKER_FILES__: Record<string, string> | undefined

const failedHashedFiles = new Set<string>()

function hashedFileName(fileName: string): string | undefined {
    if (typeof __POSTHOG_WORKER_FILES__ === 'undefined' || failedHashedFiles.has(fileName)) {
        return undefined
    }
    return __POSTHOG_WORKER_FILES__[fileName]
}

/** The deploy overwrites a fixed-name file in place, so a tab open across deploys must load the worker of its own build. */
export function createWorker(fileName: string, options: WorkerOptions): Worker {
    const hashedName = hashedFileName(fileName)
    if (!hashedName) {
        return new Worker(`/static/${fileName}`, options)
    }

    const worker = new Worker(`/static/${hashedName}`, options)
    let answered = false
    worker.addEventListener('message', () => (answered = true), { once: true })
    // A deployment that serves /static/ from the image drops the old hashed file on upgrade. An error
    // before the first answer means the file did not load, so later workers use the fixed name.
    worker.addEventListener(
        'error',
        () => {
            if (!answered) {
                failedHashedFiles.add(fileName)
            }
        },
        { once: true }
    )
    return worker
}
