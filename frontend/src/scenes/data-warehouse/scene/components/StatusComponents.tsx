import { IconCheckCircle } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { IconCancel, IconExclamation, IconRadioButtonUnchecked, IconSync } from 'lib/lemon-ui/icons'

export function StatusIcon({ status }: { status?: string }): JSX.Element {
    const s = (status || '').toLowerCase()

    if (s === 'failed' || s === 'error') {
        return <IconCancel className="text-danger" />
    }
    if (s === 'warning' || s.includes('billing')) {
        return <IconExclamation className="text-warning" />
    }
    if (s === 'running') {
        return <IconSync className="animate-spin" />
    }
    if (s === 'completed' || s === 'success') {
        return <IconCheckCircle className="text-success" />
    }
    return <IconRadioButtonUnchecked className="text-muted" />
}

export function StatusTag({ status }: { status?: string }): JSX.Element {
    const s = (status || '').toLowerCase()

    const type = ['failed', 'error'].includes(s)
        ? ('danger' as const)
        : s === 'warning'
          ? ('warning' as const)
          : ['completed', 'success'].includes(s)
            ? ('success' as const)
            : s === 'running'
              ? ('none' as const)
              : ('muted' as const)

    const size = (['completed', 'failed', 'error'].includes(s) ? 'medium' : 'small') as 'medium' | 'small'

    return (
        <LemonTag
            size={size}
            type={type}
            className="px-1 rounded-lg"
            style={type === 'none' ? { color: '#3b82f6', borderColor: '#3b82f6' } : undefined}
        >
            {s || '—'}
        </LemonTag>
    )
}
