import {
    Badge,
    Button,
    Card,
    CardContent,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Field,
    FieldLabel,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Textarea,
} from '@posthog/quill'

import type { SupportPlaybookEditorProps } from './SupportPlaybookEditor'

export function QuillSupportPlaybookEditor({
    inheritedInstructions,
    draft,
    isCustomized,
    maxChars,
    saving,
    loading,
    error,
    resetDisabledReason,
    saveDisabledReason,
    onDraftChange,
    onSave,
    onReset,
}: Omit<SupportPlaybookEditorProps, 'dirty' | 'onReset'> & {
    resetDisabledReason: string | undefined
    saveDisabledReason: string | undefined
    onReset: () => void
}): JSX.Element {
    if (loading && !inheritedInstructions) {
        return (
            <Card size="sm" className="max-w-200">
                <CardContent className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-24 w-full" />
                </CardContent>
            </Card>
        )
    }

    if (error && !inheritedInstructions) {
        return (
            <Item tone="destructive" size="sm" className="max-w-200">
                <ItemContent>
                    <ItemDescription>{error}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <Card size="sm" className="max-w-200">
            <CardContent className="flex flex-col gap-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Badge variant={isCustomized ? 'info' : 'default'}>
                        {isCustomized ? 'Customized' : 'Using default instructions'}
                    </Badge>
                    {isCustomized && (
                        <Button
                            variant="outline"
                            onClick={onReset}
                            loading={saving}
                            disabledReason={resetDisabledReason}
                            data-attr="support-playbook-reset"
                        >
                            Reset to default
                        </Button>
                    )}
                </div>
                {inheritedInstructions ? (
                    <Collapsible defaultOpen={!isCustomized}>
                        <CollapsibleTrigger>Default instructions</CollapsibleTrigger>
                        <CollapsibleContent>
                            <pre className="m-0 whitespace-pre-wrap text-xs text-muted-foreground">
                                {inheritedInstructions}
                            </pre>
                        </CollapsibleContent>
                    </Collapsible>
                ) : null}
                <Field>
                    <FieldLabel htmlFor="support-playbook-editor">Team instructions</FieldLabel>
                    <Textarea
                        id="support-playbook-editor"
                        value={draft}
                        onChange={(event) => onDraftChange(event.target.value)}
                        placeholder="Optional extra instructions for your team"
                        rows={6}
                        maxLength={maxChars}
                        disabled={saving}
                        data-attr="support-playbook-editor"
                    />
                </Field>
                <div>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="support-playbook-save"
                    >
                        Save playbook
                    </Button>
                </div>
            </CardContent>
        </Card>
    )
}
