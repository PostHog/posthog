import { REGEX_WORKER_SOURCE } from './regexWorkerSource'

export interface RegexCheck {
    pattern: string
    flags?: string
    subject: string
}

export type RegexCheckResult = { matches: boolean } | { error: 'syntax_error' }
export type RegexMatchingError = 'timeout' | 'startup_timeout' | 'unavailable' | 'worker_error' | 'canceled' | 'hidden'
export type RegexMatchingResult =
    | { status: 'success'; results: RegexCheckResult[] }
    | { status: 'error'; error: RegexMatchingError }

export interface RegexMatchingRequest {
    promise: Promise<RegexMatchingResult>
    cancel: () => void
}

export function startRegexMatching(checks: RegexCheck[]): RegexMatchingRequest {
    let worker: Worker | undefined
    let url: string | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let settled = false
    let ready = false
    let deadline = 0
    let resolve: (result: RegexMatchingResult) => void
    const promise = new Promise<RegexMatchingResult>((done) => {
        resolve = done
    })

    const finish = (result: RegexMatchingResult): void => {
        if (settled) {
            return
        }
        settled = true
        clearTimeout(timer)
        document.removeEventListener('visibilitychange', onVisibilityChange)
        if (worker) {
            worker.onmessage = null
            worker.onerror = null
            worker.onmessageerror = null
            worker.terminate()
        }
        if (url) {
            URL.revokeObjectURL(url)
        }
        resolve(result)
    }
    const fail = (error: RegexMatchingError): void => finish({ status: 'error', error })
    const onVisibilityChange = (): void => {
        if (document.hidden) {
            fail('hidden')
        }
    }

    try {
        if (document.hidden) {
            fail('hidden')
        } else if (typeof Worker === 'undefined' || typeof URL.createObjectURL !== 'function') {
            fail('unavailable')
        } else {
            url = URL.createObjectURL(new Blob([REGEX_WORKER_SOURCE], { type: 'text/javascript' }))
            worker = new Worker(url)
            deadline = performance.now() + 5000
            timer = setTimeout(() => fail('startup_timeout'), 5000)
            document.addEventListener('visibilitychange', onVisibilityChange)
            worker.onerror = () => fail('worker_error')
            worker.onmessageerror = () => fail('worker_error')
            worker.onmessage = ({ data }: MessageEvent): void => {
                if (performance.now() >= deadline) {
                    fail(ready ? 'timeout' : 'startup_timeout')
                    return
                }
                if (!ready && data?.type === 'ready') {
                    ready = true
                    clearTimeout(timer)
                    deadline = performance.now() + 100
                    timer = setTimeout(() => fail('timeout'), 100)
                    try {
                        worker!.postMessage({ checks })
                    } catch {
                        fail('worker_error')
                    }
                } else if (
                    ready &&
                    data?.type === 'result' &&
                    Array.isArray(data.results) &&
                    data.results.length === checks.length &&
                    data.results.every(
                        (result: RegexCheckResult) =>
                            result &&
                            typeof result === 'object' &&
                            (('matches' in result && typeof result.matches === 'boolean') ||
                                ('error' in result && result.error === 'syntax_error'))
                    )
                ) {
                    finish({ status: 'success', results: data.results })
                } else {
                    fail('worker_error')
                }
            }
        }
    } catch {
        fail('unavailable')
    }
    return { promise, cancel: () => fail('canceled') }
}

export function regexMatchingErrorMessage(error: RegexMatchingError): string {
    switch (error) {
        case 'timeout':
            return 'This preview took too long. Simplify the patterns or test a shorter value.'
        case 'hidden':
        case 'canceled':
            return 'This preview was canceled. Change the test value or a pattern to run it again.'
        case 'unavailable':
        case 'startup_timeout':
        case 'worker_error':
            return 'This preview could not start or finish. Check that your browser allows web workers and blob: worker sources, then change the test value to try again.'
    }
}
