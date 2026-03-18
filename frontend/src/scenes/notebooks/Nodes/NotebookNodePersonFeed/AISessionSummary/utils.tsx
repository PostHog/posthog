import { IconCheck, IconX } from '@posthog/icons'

export function formatDuration(seconds: number): string {
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    if (remainingSeconds === 0) {
        return `${minutes}m`
    }
    return `${minutes}m ${remainingSeconds}s`
}

export function getIcon(success: boolean): JSX.Element {
    return success ? <IconCheck className="text-success" /> : <IconX className="text-error" />
}
