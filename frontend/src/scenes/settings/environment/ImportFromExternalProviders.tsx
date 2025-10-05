import { ExternalProviderImportWizard } from 'scenes/import-external-providers/ExternalProviderImportWizard'

export function ImportFromExternalProviders(): JSX.Element {
    return <ExternalProviderImportWizard importType="feature-flags" />
}