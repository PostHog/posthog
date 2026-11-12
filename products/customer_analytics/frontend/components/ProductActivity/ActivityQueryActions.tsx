import { LemonButton } from '@posthog/lemon-ui'

export function ActivityQueryActions({
    loading,
    runError,
    saveError,
    onRun,
    onSave,
    onCancel,
    dataAttributes,
}: {
    loading: boolean
    runError?: string
    saveError?: string | null
    onRun: () => void
    onSave: () => void
    onCancel: () => void
    dataAttributes: { run: string; save: string; cancel?: string }
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2">
            <LemonButton
                type="primary"
                onClick={onRun}
                loading={loading}
                disabledReason={runError}
                data-attr={dataAttributes.run}
            >
                Run query
            </LemonButton>
            <LemonButton type="secondary" onClick={onSave} disabledReason={saveError} data-attr={dataAttributes.save}>
                Save source
            </LemonButton>
            <LemonButton type="tertiary" onClick={onCancel} data-attr={dataAttributes.cancel}>
                Cancel
            </LemonButton>
        </div>
    )
}
