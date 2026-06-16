/**
 * `<SecretAddDialog>` — captures a new key name before handing off to the
 * `<SecretEditDialog>`.
 *
 * Splitting "name the key" from "set the value" keeps the editor focused on
 * a known key (it pre-fetches set/unset status) and makes "add a key the
 * spec doesn't declare" an explicit, separately auditable action.
 */

'use client'

import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Label,
} from '@posthog/quill'

export function SecretAddDialog({
    open,
    onCancel,
    onConfirm,
}: {
    open: boolean
    onCancel: () => void
    onConfirm: (name: string) => void
}): React.ReactElement {
    const [name, setName] = useState('')
    const trimmed = name.trim()
    const valid = trimmed.length > 0 && /^[A-Za-z_][A-Za-z0-9_]*$/.test(trimmed)
    return (
        <Dialog
            open={open}
            onOpenChange={(o) => {
                if (!o) {
                    setName('')
                    onCancel()
                }
            }}
        >
            <DialogContent>
                <form
                    onSubmit={(e) => {
                        e.preventDefault()
                        if (valid) {
                            const next = trimmed
                            setName('')
                            onConfirm(next)
                        }
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>Add a custom secret</DialogTitle>
                        <DialogDescription className="text-xs">
                            Setting a value here doesn't add the key to the spec — the agent will only read it once the
                            spec lists it. Use this for ad-hoc rotations or to pre-seed before publishing.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody render={<div />} className="space-y-3 px-6 py-4">
                        <div className="space-y-1.5">
                            <Label htmlFor="custom-secret-name" className="text-xs">
                                Key name
                            </Label>
                            <Input
                                id="custom-secret-name"
                                autoFocus
                                value={name}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                                    setName(e.currentTarget.value.toUpperCase())
                                }
                                placeholder="MY_API_KEY"
                                spellCheck={false}
                            />
                            {!valid && trimmed.length > 0 ? (
                                <p className="text-[0.6875rem] text-warning-foreground">
                                    Letters, numbers, underscore. Must start with a letter or underscore.
                                </p>
                            ) : null}
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => {
                                setName('')
                                onCancel()
                            }}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={!valid}>
                            Continue
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
