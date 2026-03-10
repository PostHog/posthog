const THROTTLE_CAPTURE_KEY = new Set<string>()
export function throttleCapture(key: string, fn: () => void): void {
    if (!THROTTLE_CAPTURE_KEY.has(key)) {
        fn()
        THROTTLE_CAPTURE_KEY.add(key)
    }
}
export function clearThrottle(): void {
    THROTTLE_CAPTURE_KEY.clear()
}
