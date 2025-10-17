// when we capture in a loop, we don't want to capture the same error twice
// since we loop over large datasets we risk capturing the same error multiple times
// so we use a set to throttle the errors
const THROTTLE_CAPTURE_KEY = new Set<string>()
export function throttleCapture(key: string, fn: () => void): void {
    if (!THROTTLE_CAPTURE_KEY.has(key)) {
        fn()
        THROTTLE_CAPTURE_KEY.add(key)
    }
}
// only for testing
export function clearThrottle(): void {
    THROTTLE_CAPTURE_KEY.clear()
}
