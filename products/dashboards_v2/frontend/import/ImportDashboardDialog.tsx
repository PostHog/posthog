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
    const [readError, setReadError] = useState<string | null>(null)
    const [reading, setReading] = useState(false)
    const fileInput = useRef<HTMLInputElement>(null)
    // Bumped by every edit and close, so a file read that finishes later can't overwrite newer input.
    const inputVersion = useRef(0)
    const replaceText = (next: string): void => {
        inputVersion.current += 1
        setReading(false)
        setReadError(null)
        setText(next)
    }
    const readFile = (file: File): void => {
        const version = ++inputVersion.current
        setReading(true)
        file.text().then(
            (contents) => {
                if (version === inputVersion.current) {
                    setReading(false)
                    setReadError(null)
                    setText(contents)
                }
            },
            () => {
                if (version === inputVersion.current) {
                    setReading(false)
                    setText('')
                    setReadError(`Couldn't read ${file.name}. Try uploading it again.`)
                }
            }
        )
    }
    const result = useMemo(() => (text.trim() ? importDashboard(text) : null), [text])
    const close = (): void => {
        replaceText('')
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
                        onChange={(event) => replaceText(event.target.value)}
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
                                if (file) {
                                    readFile(file)
                                }
                            }}
                        />
                    </div>
                    {readError && <p className="m-0 text-sm text-danger">{readError}</p>}
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
                            reading
                                ? 'Reading the file'
                                : result && 'dashboard' in result
                                  ? undefined
                                  : 'Paste or upload a dashboard first'
                        }
                        onClick={() => {
                            if (!reading && result && 'dashboard' in result) {
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
