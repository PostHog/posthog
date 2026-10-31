import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

// Matches AGENT_INSTRUCTIONS_MAX_LENGTH on the backend, which rejects anything longer.
const MAX_LENGTH = 20_000

interface InstructionsEditorProps {
    stored: string | null
    value: string
    dirty: boolean
    loading: boolean
    placeholder: string
    onChange: (value: string) => void
    onSave: () => void
    onDiscard?: () => void
    discardDataAttr?: string
    restrictionReason?: string | null
    dataAttr: string
    ariaLabel?: string
}

export function InstructionsEditor({
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
            <LemonSkeleton className="h-32 w-full" />
        ) : (
            <p className="text-danger mb-0">Couldn't load these instructions. Refresh the page to try again.</p>
        )
    }

    return (
        <LemonTextArea
            className="[&>textarea]:p-4 [&>textarea]:leading-relaxed"
            value={value}
            onChange={onChange}
            placeholder={placeholder}
            minRows={7}
            maxRows={24}
            maxLength={MAX_LENGTH}
            disabled={!!restrictionReason || loading}
            data-attr={`${dataAttr}-input`}
            aria-label={ariaLabel}
            footer={
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-b border-t bg-surface-secondary px-3 py-2">
                    <span
                        className={cn(
                            'text-xs tabular-nums',
                            value.length >= MAX_LENGTH ? 'text-danger' : 'text-secondary'
                        )}
                        translate="no"
                    >
                        {value.length.toLocaleString()} / {MAX_LENGTH.toLocaleString()}
                    </span>
                    <div className="ml-auto flex flex-wrap items-center gap-1">
                        {dirty && (
                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={onDiscard ?? (() => onChange(stored))}
                                disabled={!!restrictionReason || loading}
                                data-attr={discardDataAttr ?? `${dataAttr}-discard`}
                            >
                                Discard
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={onSave}
                            loading={loading}
                            disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
                            data-attr={`${dataAttr}-save`}
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        />
    )
}
