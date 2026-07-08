import { IntegrationFullPage } from './IntegrationFullPage'
import { Integration, IntegrationDefinition, SettingsSectionComponent } from './integrationTypes'

export type { Integration, IntegrationDefinition, SettingsSectionComponent } from './integrationTypes'

export function defineIntegration(
    definition: IntegrationDefinition,
    SettingsSection: SettingsSectionComponent
): Integration {
    return {
        ...definition,
        SettingsSection,
        FullPage: () => <IntegrationFullPage definition={definition} SettingsSection={SettingsSection} />,
    }
}
