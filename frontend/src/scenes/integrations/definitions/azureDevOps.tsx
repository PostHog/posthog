import { ICONS } from 'lib/integrations/utils'

import { AzureDevOpsIntegration } from '../components/Integrations'
import { defineIntegration } from '../integrationDefinition'

export const AzureDevOps = defineIntegration(
    {
        slug: 'azure-devops',
        kind: 'azure-devops',
        name: 'Azure DevOps',
        logo: ICONS['azure-devops'],
        subtitle: 'Connect your Azure DevOps repositories to PostHog',
        description:
            'Connect an Azure DevOps project so PostHog can discover repositories and open code changes through a shared code-host interface.',
        capabilities: [
            'Browse repositories in an Azure DevOps project',
            'Create branches for code changes',
            'Open pull requests against the default branch',
        ],
        docsUrl: 'https://learn.microsoft.com/azure/devops/repos/',
    },
    AzureDevOpsIntegration
)
