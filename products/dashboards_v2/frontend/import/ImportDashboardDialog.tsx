import { useMemo, useRef, useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Textarea,
} from '@posthog/quill'

import type { Dashboard } from '../dashboard/dashboardTypes'
import { importDashboard } from './importDashboard'
import { ImportReportSummary } from './ImportReportSummary'

export function ImportDashboardDialog({
    open,
    onClose,
    onOpenBoard,
}: {
    open: boolean
    onClose: () => void
    onOpenBoard: (dashboard: Dashboard) => void
}): JSX.Element {
    const [text, setText] = useState('')
    const fileInput = useRef<HTMLInputElement>(null)
    const result = useMemo(() => (text.trim() ? importDashboard(text) : null), [text])
    const close = (): void => {
        setText('')
        onClose()
    }

    return (
        <Dialog open={open} onOpenChange={(isOpen) => !isOpen && close()}>
            <DialogContent size="wide" data-attr="dashboard-v2-import">
                <DialogHeader>
                    <DialogTitle>Import a dashboard</DialogTitle>
                    <DialogDescription>
                        Paste or upload a Grafana or New Relic dashboard's JSON. Queries are converted to run on
                        PostHog, and anything that can't be is kept as a note on its tile.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-3">
                    <Textarea
                        aria-label="Dashboard JSON"
                        placeholder='{"title": "...", "panels": [...]}'
                        className="font-mono text-xs min-h-40 max-h-60"
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        data-attr="dashboard-v2-import-json"
                    />
                    <div>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => fileInput.current?.click()}
                            data-attr="dashboard-v2-import-upload"
                        >
                            Upload a file
                        </Button>
                        <input
                            ref={fileInput}
                            type="file"
                            accept=".json,.txt,application/json,text/plain"
                            className="hidden"
                            onChange={(event) => {
                                const file = event.target.files?.[0]
                                event.target.value = ''
                                void file?.text().then(setText)
                            }}
                        />
                    </div>
                    {result && 'error' in result && <p className="m-0 text-sm text-danger">{result.error}</p>}
                    {result && 'report' in result && (
                        <div className="max-h-80 overflow-y-auto">
                            <ImportReportSummary report={result.report} />
                        </div>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close} data-attr="dashboard-v2-import-cancel">
                        Cancel
                    </Button>
                    {/* TODO(https://github.com/PostHog/posthog/pull/142503): save the board once boards are stored. */}
                    <Button
                        variant="primary"
                        disabledReason={
                            result && 'dashboard' in result ? undefined : 'Paste or upload a dashboard first'
                        }
                        onClick={() => {
                            if (result && 'dashboard' in result) {
                                onOpenBoard(result.dashboard)
                                close()
                            }
                        }}
                        data-attr="dashboard-v2-import-open"
                    >
                        Open board
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
