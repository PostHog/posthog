import { Button, InputGroup, InputGroupAddon, InputGroupTextarea, Skeleton, Text } from '@posthog/quill'

import { MAX_LENGTH, InstructionsEditorProps } from './InstructionsEditor'

export function QuillInstructionsEditor({
    stored,
    value,
    dirty,
    loading,
    placeholder,
    onChange,
    onSave,
    onDiscard,
    discardDataAttr,
    restrictionReason,
    dataAttr,
    ariaLabel,
}: InstructionsEditorProps): JSX.Element {
    if (stored === null) {
        return loading ? (
            <Skeleton className="h-32 w-full" />
        ) : (
            <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                Couldn't load these instructions. Refresh the page to try again.
            </Text>
        )
    }

    return (
        <InputGroup>
            <InputGroupTextarea
                className="min-h-40 max-h-128 overflow-y-auto p-4 leading-relaxed"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                placeholder={placeholder}
                maxLength={MAX_LENGTH}
                disabled={loading}
                disabledReason={restrictionReason}
                data-attr={`${dataAttr}-input`}
                aria-label={ariaLabel}
            />
            <InputGroupAddon align="block-end" className="flex-wrap justify-between gap-2 border-t">
                <Text
                    size="xs"
                    variant={value.length >= MAX_LENGTH ? 'destructive' : 'muted'}
                    className="tabular-nums"
                    render={<span />}
                    translate="no"
                >
                    {`${value.length.toLocaleString()} / ${MAX_LENGTH.toLocaleString()}`}
                </Text>
                <div className="ml-auto flex flex-wrap items-center gap-1">
                    {dirty && (
                        <Button
                            onClick={onDiscard ?? (() => onChange(stored))}
                            disabled={loading}
                            disabledReason={restrictionReason}
                            data-attr={discardDataAttr ?? `${dataAttr}-discard`}
                        >
                            Discard
                        </Button>
                    )}
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={loading}
                        disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
                        data-attr={`${dataAttr}-save`}
                    >
                        Save
                    </Button>
                </div>
            </InputGroupAddon>
        </InputGroup>
    )
}
