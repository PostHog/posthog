/**
 * Opt-in stdout for sampling pipeline inspection. Enable with `LOGS_SAMPLING_DEBUG=1`.
 * TODO(team-logs): delete this file and all imports before merge if you do not want debug hooks in tree.
 */
export function isLogsSamplingDebugEnabled(): boolean {
    return process.env.LOGS_SAMPLING_DEBUG === '1'
}

export function logsSamplingDebugLog(...args: unknown[]): void {
    if (!isLogsSamplingDebugEnabled()) {
        return
    }

    console.log('[logs-sampling]', new Date().toISOString(), ...args)
}
