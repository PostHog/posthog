import { useId } from 'react'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import type { ProviderKeyDependentConfigsApi } from '../generated/api.schemas'

export interface QuillDeleteKeyDialogProps {
    keyName: string
    dependentConfigs: ProviderKeyDependentConfigsApi | null
    dependentConfigsLoading: boolean
    hasEvaluations: boolean
    hasAlternatives: boolean
    replacementOptions: { value: string; label: string }[]
    replacementKeyId: string | undefined
    onReplacementKeyChange: (keyId: string) => void
    onClose: () => void
    onDelete: () => void
    deleteLoading: boolean
    restrictionReason: string | null
}

export function QuillDeleteKeyDialog({
    keyName,
    dependentConfigs,
    dependentConfigsLoading,
    hasEvaluations,
    hasAlternatives,
    replacementOptions,
    replacementKeyId,
    onReplacementKeyChange,
    onClose,
    onDelete,
    deleteLoading,
    restrictionReason,
}: QuillDeleteKeyDialogProps): JSX.Element {
    const replacementId = useId()
    const evaluations = dependentConfigs?.evaluations ?? []

    return (
        <AlertDialog open onOpenChange={(nextOpen: boolean) => !nextOpen && onClose()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete API key?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Are you sure you want to delete "<strong>{keyName}</strong>"? This cannot be undone.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                {dependentConfigsLoading ? (
                    <Skeleton className="h-20" />
                ) : (
                    <div className="flex flex-col gap-4">
                        {hasEvaluations && (
                            <Item variant="outline" size="sm">
                                <ItemContent>
                                    <ItemTitle>
                                        {evaluations.length} evaluation
                                        {evaluations.length === 1 ? '' : 's'} using this key:
                                    </ItemTitle>
                                    <Text
                                        size="xs"
                                        variant="muted"
                                        render={
                                            <ul className="m-0 flex max-h-48 list-disc flex-col gap-1 overflow-y-auto pl-4" />
                                        }
                                    >
                                        {evaluations.map((evaluation) => (
                                            <li key={evaluation.id}>{evaluation.name}</li>
                                        ))}
                                    </Text>
                                </ItemContent>
                            </Item>
                        )}

                        {hasEvaluations && hasAlternatives && (
                            <Field>
                                <FieldLabel htmlFor={replacementId}>Replace with another key</FieldLabel>
                                <Select
                                    items={replacementOptions}
                                    value={replacementKeyId ?? null}
                                    onValueChange={(value) => value && onReplacementKeyChange(value as string)}
                                >
                                    <SelectTrigger id={replacementId} className="w-full">
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {replacementOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <FieldDescription>
                                    The selected key will be used by evaluations that currently use this key.
                                </FieldDescription>
                            </Field>
                        )}

                        {hasEvaluations && !hasAlternatives && (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        <strong>No replacement keys available.</strong> These evaluations will be
                                        disabled after deletion.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                    </div>
                )}
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <Button
                        variant="destructive-outline"
                        onClick={onDelete}
                        loading={deleteLoading}
                        disabled={dependentConfigsLoading}
                        disabledReason={restrictionReason}
                    >
                        Delete key
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
