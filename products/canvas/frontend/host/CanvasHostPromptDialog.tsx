import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Text,
} from '@posthog/quill'

import { CanvasHostPrompt, canvasHostLogic } from './canvasHostLogic'

interface PromptCopy {
    title: string
    description: string
    confirm: string
    destructive?: boolean
}

function promptCopy(prompt: CanvasHostPrompt): PromptCopy {
    switch (prompt.kind) {
        case 'connector':
            return prompt.request.reason === 'tool'
                ? {
                      title: 'Allow this tool call?',
                      description:
                          'This tool is set to ask for permission. Allow only this call. Your saved tool permissions will not change.',
                      confirm: 'Allow once',
                  }
                : {
                      title: 'Allow this canvas to use your connection?',
                      description:
                          'This canvas wants to read data with your connection. Only allow canvases you trust.',
                      confirm: 'Allow access',
                  }
        case 'agent-request':
            return {
                title: 'Ask the canvas agent to make this change?',
                description:
                    'Review the exact request. Accepting starts an agent run that uses compute. The result arrives as a draft for review.',
                confirm: 'Accept and run',
            }
        case 'action':
            return {
                title: 'Let this canvas make this change?',
                description:
                    prompt.request.action.verb === 'tasks.create_and_run'
                        ? 'Review this request. Accepting starts a cloud task that uses paid compute.'
                        : 'Review this request before the canvas makes a change on your behalf.',
                confirm: 'Continue',
                destructive: prompt.request.action.destructive,
            }
        case 'external-link':
            return {
                title: 'Open this link?',
                description: 'The canvas wants to open a page in a new tab.',
                confirm: 'Open link',
            }
    }
}

function PromptDetails({ prompt }: { prompt: CanvasHostPrompt }): JSX.Element {
    switch (prompt.kind) {
        case 'connector':
            return (
                <div className="flex flex-col gap-2">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded border border-border p-3">
                        <dt>
                            <Text size="sm">Connection</Text>
                        </dt>
                        <dd className="break-all">
                            <Text size="sm">{prompt.request.provider}</Text>
                        </dd>
                        <dt>
                            <Text size="sm">Tool</Text>
                        </dt>
                        <dd className="break-all font-mono">
                            <Text size="sm">{prompt.request.tool}</Text>
                        </dd>
                    </dl>
                    {prompt.request.reason === 'tool' && (
                        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded border border-border p-3 text-xs">
                            {JSON.stringify(prompt.request.arguments ?? {}, null, 2)}
                        </pre>
                    )}
                    <Text size="sm" variant="muted">
                        The canvas can receive private data and share it through its declared capabilities.
                    </Text>
                </div>
            )
        case 'agent-request':
            return (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-border p-3 text-sm">
                    {prompt.prompt}
                </pre>
            )
        case 'action':
            return (
                <div className="flex flex-col gap-2">
                    <Text size="sm">{prompt.request.action.summary}</Text>
                    <Text size="sm" className="break-all font-mono">
                        {prompt.request.action.verb}
                    </Text>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded border border-border p-3 text-sm">
                        {JSON.stringify(prompt.request.payload, null, 2)}
                    </pre>
                </div>
            )
        case 'external-link':
            return (
                <Text className="break-all font-mono" size="sm">
                    {prompt.url}
                </Text>
            )
    }
}

/**
 * Asks the viewer before a canvas uses a connection, starts an agent run, runs a
 * action, or opens a link. Render it under a `BindLogic` for `canvasHostLogic`.
 */
export function CanvasHostPromptDialog(): JSX.Element {
    const { activePrompt } = useValues(canvasHostLogic)
    const { respondToPrompt } = useActions(canvasHostLogic)
    const denyRef = useRef<HTMLButtonElement>(null)
    const copy = activePrompt ? promptCopy(activePrompt) : null

    return (
        <Dialog
            open={!!activePrompt}
            onOpenChange={(open) => {
                if (!open && activePrompt) {
                    respondToPrompt(activePrompt.id, false)
                }
            }}
        >
            <DialogContent showCloseButton={false} initialFocus={denyRef}>
                {activePrompt && copy && (
                    <>
                        <DialogHeader>
                            <DialogTitle>{copy.title}</DialogTitle>
                            <DialogDescription>{copy.description}</DialogDescription>
                        </DialogHeader>
                        <DialogBody>
                            <PromptDetails prompt={activePrompt} />
                        </DialogBody>
                        <DialogFooter>
                            <Button
                                ref={denyRef}
                                variant="outline"
                                onClick={() => respondToPrompt(activePrompt.id, false)}
                                data-attr="canvas-host-prompt-deny"
                            >
                                Cancel
                            </Button>
                            <Button
                                variant={copy.destructive ? 'destructive-outline' : 'primary'}
                                onClick={() => respondToPrompt(activePrompt.id, true)}
                                data-attr={`canvas-host-prompt-allow-${activePrompt.kind}`}
                            >
                                {copy.confirm}
                            </Button>
                        </DialogFooter>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
