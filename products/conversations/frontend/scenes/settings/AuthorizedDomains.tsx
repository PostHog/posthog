import { useActions, useValues } from 'kea'
import type { ChangeEvent, KeyboardEvent } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Input,
} from 'lib/ui/quill'

import { supportSettingsLogic } from './supportSettingsLogic'

export function AuthorizedDomains(): JSX.Element {
    const { conversationsDomains, isAddingDomain, editingDomainIndex, domainInputValue } =
        useValues(supportSettingsLogic)
    const { setDomainInputValue, saveDomain, removeDomain, startEditDomain, cancelDomainEdit } =
        useActions(supportSettingsLogic)

    const saveDisabledReason = !domainInputValue.trim() ? 'Enter a domain' : undefined

    return (
        <div className="flex flex-col gap-2">
            {conversationsDomains.length === 0 && !isAddingDomain && (
                <div className="border rounded p-4 text-secondary">
                    <p className="mb-2">
                        <span className="font-bold">No domains configured.</span>
                        <br />
                        The widget and API will be accessible on all domains. Add domains to limit where they appear.
                    </p>
                    <p className="mb-0">
                        <span className="font-bold">Ticket recovery is disabled until a domain is added.</span>{' '}
                        Recovering tickets by email requires at least one authorized domain so the recovery link can
                        only point to a site you control.
                    </p>
                </div>
            )}

            {(isAddingDomain || editingDomainIndex !== null) && (
                <div className="border rounded p-2 bg-surface-primary">
                    <div className="gap-2">
                        <Input
                            autoFocus
                            className="w-full"
                            value={domainInputValue}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setDomainInputValue(e.target.value)}
                            placeholder="https://example.com or https://*.example.com"
                            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                                if (e.key === 'Enter') {
                                    saveDomain(domainInputValue, editingDomainIndex)
                                } else if (e.key === 'Escape') {
                                    cancelDomainEdit()
                                }
                            }}
                        />
                        <div className="flex gap-2 mt-2">
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={() => saveDomain(domainInputValue, editingDomainIndex)}
                                disabled={!!saveDisabledReason}
                                title={saveDisabledReason}
                            >
                                Save
                            </Button>
                            <Button variant="outline" size="sm" onClick={cancelDomainEdit}>
                                Cancel
                            </Button>
                        </div>
                    </div>
                </div>
            )}

            {conversationsDomains.map((domain: string, index: number) =>
                editingDomainIndex === index ? null : (
                    <div key={index} className="border rounded flex items-center p-2 pl-4 bg-surface-primary">
                        <span title={domain} className="flex-1 truncate">
                            {domain}
                        </span>
                        <div className="flex gap-1 shrink-0">
                            <Button
                                variant="default"
                                size="icon-sm"
                                onClick={() => startEditDomain(index)}
                                title="Edit"
                                aria-label="Edit"
                            >
                                <IconPencil />
                            </Button>
                            <AlertDialog>
                                <AlertDialogTrigger
                                    render={<Button variant="default" size="icon-sm" title="Remove domain" />}
                                >
                                    <IconTrash />
                                </AlertDialogTrigger>
                                <AlertDialogContent>
                                    <AlertDialogHeader>
                                        <AlertDialogTitle>Remove {domain}?</AlertDialogTitle>
                                        <AlertDialogDescription>
                                            Are you sure you want to remove this domain?
                                        </AlertDialogDescription>
                                    </AlertDialogHeader>
                                    <AlertDialogFooter>
                                        <AlertDialogClose render={<Button variant="outline" />}>
                                            Cancel
                                        </AlertDialogClose>
                                        <AlertDialogClose
                                            render={
                                                <Button variant="destructive" onClick={() => removeDomain(index)} />
                                            }
                                        >
                                            Remove
                                        </AlertDialogClose>
                                    </AlertDialogFooter>
                                </AlertDialogContent>
                            </AlertDialog>
                        </div>
                    </div>
                )
            )}
        </div>
    )
}
