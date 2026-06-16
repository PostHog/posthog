/**
 * "Run now" control for a cron trigger — fires the cron out-of-band so an
 * author can test its prompt without waiting for the schedule. Guards against
 * double-submission (disabled + spinner while in flight) and surfaces the
 * outcome inline. Rendered on a cron trigger's detail in the config explorer.
 */

import { CheckIcon, InfoIcon, Loader2Icon, PlayIcon } from 'lucide-react'
import { useState } from 'react'

export function CronFireButton({
    cronName,
    onFire,
}: {
    cronName: string
    onFire: (cronName: string) => Promise<{ session_id: string }>
}): React.ReactElement {
    const [status, setStatus] = useState<'idle' | 'firing' | 'fired' | 'error'>('idle')

    const fire = async (): Promise<void> => {
        if (status === 'firing') {
            return
        }
        setStatus('firing')
        try {
            await onFire(cronName)
            setStatus('fired')
        } catch {
            setStatus('error')
        }
    }

    const label =
        status === 'firing' ? 'Firing…' : status === 'fired' ? 'Fired' : status === 'error' ? 'Failed' : 'Run now'
    const StatusIcon =
        status === 'firing' ? Loader2Icon : status === 'fired' ? CheckIcon : status === 'error' ? InfoIcon : PlayIcon

    return (
        <button
            type="button"
            onClick={fire}
            disabled={status === 'firing'}
            title={`Fire the "${cronName}" cron now`}
            className={
                'flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wide transition-colors disabled:opacity-60 ' +
                (status === 'error'
                    ? 'border-red-500/50 text-red-600 hover:border-red-500'
                    : 'border-border bg-card text-muted-foreground hover:border-foreground/40 hover:text-foreground')
            }
        >
            <StatusIcon className={'h-3 w-3' + (status === 'firing' ? ' animate-spin' : '')} />
            {label}
        </button>
    )
}
