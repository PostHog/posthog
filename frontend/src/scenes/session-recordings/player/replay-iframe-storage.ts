export const ReplayIframeDatakeyPrefix = 'ph_replay_fixed_heatmap_'

export function removeFromLocalStorageWithPrefix(prefix: string): void {
    for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (key?.startsWith(prefix)) {
            localStorage.removeItem(key)
        }
    }
}

export function removeReplayIframeDataFromLocalStorage(): void {
    removeFromLocalStorageWithPrefix(ReplayIframeDatakeyPrefix)
}
