import { useValues } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationCustomAssets(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const customAssets = currentOrganization?.custom_assets ?? []

    // Subtle by design: render nothing unless the org actually has custom assets.
    if (customAssets.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <span className="text-muted text-xs">Custom assets</span>
            <div className="flex flex-wrap gap-4">
                {customAssets.map((asset) => (
                    <div key={asset.id} className="flex flex-col items-center gap-1">
                        <img
                            src={asset.url}
                            alt={asset.key}
                            title={asset.file_name ?? asset.key}
                            className="h-10 w-auto rounded border object-contain"
                        />
                        <span className="text-muted text-xs">{asset.key}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}
