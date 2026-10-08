import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

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
    restrictionReason?: string | null
    dataAttr: string
}

export function InstructionsEditor({
    stored,
    value,
    dirty,
    loading,
    placeholder,
    onChange,
    onSave,
    restrictionReason,
    dataAttr,
}: InstructionsEditorProps): JSX.Element {
    if (stored === null) {
        return loading ? (
            <LemonSkeleton className="h-32 w-full" />
        ) : (
            <p className="text-danger mb-0">Couldn't load these instructions. Refresh the page to try again.</p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonTextArea
                value={value}
                onChange={onChange}
                placeholder={placeholder}
                minRows={6}
                maxRows={24}
                maxLength={MAX_LENGTH}
                disabled={!!restrictionReason || loading}
                data-attr={`${dataAttr}-input`}
            />
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="primary"
                    onClick={onSave}
                    loading={loading}
                    disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
                    data-attr={`${dataAttr}-save`}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
