import type { LemonTagType } from '@posthog/lemon-ui'

const STATUS_COPY: Record<string, { label: string; type: LemonTagType }> = {
    draft: { label: 'Draft', type: 'muted' },
    scanning: { label: 'Checking', type: 'warning' },
    scan_failed: { label: 'Check failed', type: 'danger' },
    building: { label: 'Building', type: 'warning' },
    build_failed: { label: 'Build failed', type: 'danger' },
    ready: { label: 'Ready', type: 'success' },
}

export function cloudImageStatus(status: string): { label: string; type: LemonTagType } {
    return STATUS_COPY[status] ?? { label: status, type: 'default' }
}
