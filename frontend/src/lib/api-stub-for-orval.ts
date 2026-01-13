/**
 * Stub for orval's esbuild bundling step.
 *
 * Orval v8 bundles mutator files with esbuild to parse function signatures.
 * The real lib/api imports scss files which esbuild can't handle.
 * This stub provides the same interface without the scss dependency chain.
 *
 * This file is NEVER executed - it's only used during orval type generation.
 */

type ApiMethodOptions = {
    signal?: AbortSignal
    headers?: Record<string, string>
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
const api = {
    get: async function <T = any>(url: string, options?: ApiMethodOptions): Promise<T> {
        void url
        void options
        throw new Error('Stub - should never be called')
    },
    create: async function <T = any, P = any>(url: string, data?: P, options?: ApiMethodOptions): Promise<T> {
        void url
        void data
        void options
        throw new Error('Stub - should never be called')
    },
    update: async function <T = any, P = any>(url: string, data: P, options?: ApiMethodOptions): Promise<T> {
        void url
        void data
        void options
        throw new Error('Stub - should never be called')
    },
    put: async function <T = any, P = any>(url: string, data: P, options?: ApiMethodOptions): Promise<T> {
        void url
        void data
        void options
        throw new Error('Stub - should never be called')
    },
    delete: async function (url: string): Promise<any> {
        void url
        throw new Error('Stub - should never be called')
    },
}

export default api
