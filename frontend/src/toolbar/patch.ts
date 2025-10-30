// import { patch } from 'rrweb/typings/utils'
// copied from https://github.com/rrweb-io/rrweb/blob/8aea5b00a4dfe5a6f59bd2ae72bb624f45e51e81/packages/rrweb/src/utils.ts#L129
// which was copied from https://github.com/getsentry/sentry-javascript/blob/b2109071975af8bf0316d3b5b38f519bdaf5dc15/packages/utils/src/object.ts

export function patch(
    source: { [key: string]: any },
    name: string,
    replacement: (...args: unknown[]) => unknown,
    // in case we want to wrap something more than once
    patchKey: string
): () => void {
    try {
        if (!(name in source)) {
            return () => {
                //
            }
        }

        const original = source[name] as () => unknown
        const wrapped = replacement(original)

        // Make sure it's a function first, as we need to attach an empty prototype for `defineProperties` to work
        // otherwise it'll throw "TypeError: Object.defineProperties called on non-object"
        if (typeof wrapped === 'function') {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
            wrapped.prototype = wrapped.prototype || {}
            Object.defineProperties(wrapped, {
                [patchKey]: {
                    enumerable: false,
                    value: true,
                },
            })
        }

        source[name] = wrapped

        return () => {
            source[name] = original
        }
    } catch {
        return () => {
            //
        }
        // This can throw if multiple fill happens on a global object like XMLHttpRequest
        // Fixes https://github.com/getsentry/sentry-javascript/issues/2043
    }
}
