import { useEffect, useRef, useState } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Dot,
    Text,
} from '@posthog/quill'

type Check = { key: string; label: string; ok: boolean }

const CHECKS: Check[] = [
    { key: 'traces', label: 'Traces are arriving', ok: true },
    { key: 'costs', label: 'Model costs are captured', ok: true },
    { key: 'users', label: 'Generations are linked to people', ok: false },
    { key: 'sessions', label: 'Generations are linked to sessions', ok: false },
]

const SCAN_MS = 1200

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function InstrumentationChecklist(): JSX.Element {
    const [dismissed, setDismissed] = useState<string[]>([])
    const [scanning, setScanning] = useState(false)
    const [scans, setScans] = useState(0)
    const timer = useRef<ReturnType<typeof setTimeout>>()
    useEffect(() => () => clearTimeout(timer.current), [])
    const failing = CHECKS.filter((check) => !check.ok && !dismissed.includes(check.key))
    const rescan = (): void => {
        setScanning(true)
        timer.current = setTimeout(() => {
            setScanning(false)
            setScans((count) => count + 1)
        }, SCAN_MS)
    }
    return (
        <Collapsible defaultOpen={failing.length > 0} className="flex h-full flex-col gap-2">
            <CollapsibleHeader>
                <CollapsibleTrigger iconOnly>Toggle checks</CollapsibleTrigger>
                <Text size="sm" className="font-semibold">
                    Instrumentation
                </Text>
                <Badge variant={failing.length > 0 ? 'warning' : 'success'}>
                    {failing.length > 0 ? `${failing.length} to fix` : 'All good'}
                </Badge>
                <Button
                    size="xs"
                    className="ms-auto"
                    loading={scanning}
                    data-attr="dashboard-v2-example-rescan"
                    onClick={rescan}
                >
                    <IconRefresh />
                    Rescan
                </Button>
            </CollapsibleHeader>
            <CollapsibleContent className="flex flex-col gap-1">
                {CHECKS.filter((check) => !dismissed.includes(check.key)).map(({ key, label, ok }) => (
                    <div key={key} className="flex items-center gap-2">
                        <Dot variant={ok ? 'success' : 'warning'} />
                        <Text size="sm" variant={ok ? 'muted' : 'default'} className="flex-1">
                            {label}
                        </Text>
                        {!ok && (
                            <Button
                                size="xs"
                                variant="link-muted"
                                onClick={() => setDismissed([...dismissed, key])}
                            >
                                Dismiss
                            </Button>
                        )}
                    </div>
                ))}
                {dismissed.length > 0 && (
                    <Button size="xs" variant="link" className="self-start" onClick={() => setDismissed([])}>
                        Show {dismissed.length} dismissed
                    </Button>
                )}
                {scans > 0 && (
                    <Text size="xs" variant="muted">
                        Scanned {scans} {scans === 1 ? 'time' : 'times'} this visit.
                    </Text>
                )}
            </CollapsibleContent>
        </Collapsible>
    )
}
