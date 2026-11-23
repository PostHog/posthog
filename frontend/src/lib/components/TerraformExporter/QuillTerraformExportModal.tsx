import { useEffect, useState } from 'react'

import { IconDownload, IconX } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { CodeSnippet, Language } from '~/lib/components/CodeSnippet/CodeSnippet'
import { LinkPrimitive } from '~/lib/lemon-ui/Link'

import { QuillTerraformLockToggle } from './QuillTerraformLockToggle'
import { getBaseName, getDescription } from './TerraformExportModal'
import { TerraformExportResource, useTerraformDownload, useTerraformExport } from './useTerraformExport'

interface QuillTerraformExportModalProps {
    isOpen: boolean
    onClose: () => void
    resource: TerraformExportResource
    'data-attr'?: string
}

function QuillDescriptionLink({ to, children }: { to: string; children: React.ReactNode }): JSX.Element {
    return (
        <Button variant="link" size="inline" nativeButton={false} render={<LinkPrimitive to={to} target="_blank" />}>
            {children}
        </Button>
    )
}

export function QuillTerraformExportModal({
    isOpen,
    onClose,
    resource,
    'data-attr': dataAttr,
}: QuillTerraformExportModalProps): JSX.Element {
    const baseName = getBaseName(resource)
    const state = useTerraformExport(resource, isOpen)
    const handleDownload = useTerraformDownload(state.result, baseName)
    const [warningsDismissed, setWarningsDismissed] = useState(false)

    useEffect(() => {
        if (isOpen) {
            setWarningsDismissed(false)
        }
    }, [isOpen])

    const filename = `${baseName}.tf`
    const displayFilename = baseName.length > 30 ? `${baseName.slice(0, 30)}….tf` : filename

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent size="wide" data-attr={dataAttr}>
                <DialogHeader>
                    <DialogTitle>Manage with Terraform</DialogTitle>
                    <DialogDescription>
                        {getDescription(resource, state.result, QuillDescriptionLink)}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        {resource.type === 'access_control' && (
                            <QuillTerraformLockToggle
                                organizationId={resource.data.organizationId}
                                projectId={resource.data.projectId}
                            />
                        )}

                        {state.loading && (
                            <div className="flex flex-col gap-2">
                                <Skeleton className="h-4 w-1/2" />
                                <Skeleton className="h-32" />
                            </div>
                        )}

                        {state.error && (
                            <Item tone="destructive" size="sm">
                                <ItemContent>
                                    <ItemTitle>Error</ItemTitle>
                                    <ItemDescription>{state.error}</ItemDescription>
                                </ItemContent>
                            </Item>
                        )}

                        {state.result && (
                            <>
                                {state.result.warnings.length > 0 && !warningsDismissed && (
                                    <Item tone="warning" size="sm">
                                        <ItemContent>
                                            <ItemTitle>Warnings</ItemTitle>
                                            <ul className="m-0 flex list-disc flex-col gap-1 pl-4">
                                                {state.result.warnings.map((warning, index) => (
                                                    <Text key={index} size="xs" render={<li />}>
                                                        {warning}
                                                    </Text>
                                                ))}
                                            </ul>
                                        </ItemContent>
                                        <ItemActions>
                                            <Button
                                                size="icon-sm"
                                                aria-label="Dismiss warnings"
                                                tooltip="Dismiss warnings"
                                                onClick={() => setWarningsDismissed(true)}
                                            >
                                                <IconX />
                                            </Button>
                                        </ItemActions>
                                    </Item>
                                )}

                                <CodeSnippet language={Language.HCL} wrap thing="Terraform configuration">
                                    {state.result.hcl}
                                </CodeSnippet>
                            </>
                        )}
                    </div>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        onClick={handleDownload}
                        disabledReason={state.loading ? 'Loading...' : state.error ? 'Export failed' : undefined}
                    >
                        <IconDownload />
                        {`Download ${displayFilename}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
