import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

/** Resolves true when the user confirms a key rename, which breaks SDK calls that still use the old key. */
export function confirmFeatureFlagKeyChange(oldKey: string): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
        LemonDialog.open({
            title: 'Change flag key?',
            description: (
                <span>
                    Renaming this key will break any existing code that references it (e.g.{' '}
                    <code className="text-xs bg-fill-secondary rounded px-1 py-0.5">{`getFeatureFlag('${oldKey}')`}</code>
                    ). Make sure to update all SDK calls and integrations.
                </span>
            ),
            primaryButton: {
                children: 'Change key',
                status: 'danger',
                onClick: () => resolve(true),
            },
            secondaryButton: {
                children: 'Cancel',
            },
            onAfterClose: () => resolve(false),
        })
    })
}
