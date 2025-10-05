
import { ExternalProviderImportWizard } from 'scenes/import-external-providers/ExternalProviderImportWizard'

export function FeatureFlagMigrationScene(): JSX.Element {
    return (
        <div className="space-y-6">
            <ExternalProviderImportWizard importType="feature-flags" />
        </div>
    )
}