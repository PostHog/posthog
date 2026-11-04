import { LemonDialog } from '@posthog/lemon-ui'

import { HogFunctionConfigDiff } from './HogFunctionConfigDiff'
import { HogFunctionFieldDiff, hogFunctionFieldLabel } from './hogFunctionConfigDiffUtils'

interface HogFunctionPublishDraftDialogProps {
    diffs: HogFunctionFieldDiff[]
    changedFields: string[]
    enabled: boolean
}

function HogFunctionPublishDraftContent({
    diffs,
    changedFields,
    enabled,
}: HogFunctionPublishDraftDialogProps): JSX.Element {
    // The API masks secret values, so a draft that only stages a new secret has no visible diff.
    const hiddenChanges = changedFields.filter((field) => !diffs.some((diff) => diff.field === field))

    return (
        <div className="flex flex-col gap-3 min-w-0">
            <p className="mb-0">
                This replaces the live config with the staged changes.{' '}
                {enabled
                    ? 'New events use the published version right away.'
                    : 'It is disabled, so nothing runs until you enable it.'}
            </p>
            {changedFields.length === 0 ? (
                <p className="mb-0">The staged changes match the live config. Publishing clears the draft.</p>
            ) : (
                <>
                    {diffs.length > 0 && (
                        // Capped so a large draft scrolls inside the dialog and the publish button stays in view.
                        <div className="max-h-[60vh] overflow-y-auto">
                            <HogFunctionConfigDiff diffs={diffs} />
                        </div>
                    )}
                    {hiddenChanges.length > 0 && (
                        <p className="mb-0 text-secondary">
                            Secret values also change in:{' '}
                            {hiddenChanges.map((field) => hogFunctionFieldLabel(field)).join(', ')}. They stay hidden.
                        </p>
                    )}
                </>
            )}
        </div>
    )
}

export function openHogFunctionPublishDraftDialog({
    onConfirm,
    ...props
}: HogFunctionPublishDraftDialogProps & { onConfirm: () => void }): void {
    LemonDialog.open({
        title: 'Publish staged changes?',
        maxWidth: '48rem',
        description: <HogFunctionPublishDraftContent {...props} />,
        primaryButton: {
            children: 'Publish',
            onClick: onConfirm,
            'data-attr': 'hog-function-draft-publish-confirm',
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
