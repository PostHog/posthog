export function isObject(candidate: unknown): candidate is Record<string, unknown> {
    return typeof candidate === 'object' && candidate !== null && !Array.isArray(candidate)
}

export function isEmptyObject(candidate: unknown): boolean {
    return isObject(candidate) && Object.keys(candidate).length === 0
}

export function debounce<F extends (...args: Parameters<F>) => ReturnType<F>>(
    func: F,
    waitFor: number
): (...args: Parameters<F>) => void {
    let timeout: ReturnType<typeof setTimeout>
    return (...args: Parameters<F>): void => {
        clearTimeout(timeout)
        timeout = setTimeout(() => func(...args), waitFor)
    }
}

export const base64ArrayBuffer = (encodedString: string): ArrayBufferLike => {
    const binString = atob(encodedString)
    const data = new Uint8Array(binString.length)
    for (let i = 0; i < binString.length; i++) {
        data[i] = binString.charCodeAt(i)
    }
    return data.buffer
}
