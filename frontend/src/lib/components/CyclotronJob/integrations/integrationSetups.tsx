import { AzureBlobSetupModal } from 'scenes/integrations/azure-blob/AzureBlobSetupModal'
import { DatabricksSetupModal } from 'scenes/integrations/databricks/DatabricksSetupModal'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { urls } from 'scenes/urls'

import { ChannelSetupModal } from 'products/workflows/frontend/Channels/ChannelSetupModal'

import { registerIntegrationSetup } from './integrationSetupRegistry'

registerIntegrationSetup({
    kind: ['google-pubsub', 'google-cloud-storage', 'firebase'],
    menuItem: ({ kind, uploadKey }) => ({
        label:
            kind === 'firebase'
                ? 'Upload Firebase service account .json key file'
                : 'Upload Google Cloud .json key file',
        onClick: () => uploadKey(kind),
    }),
})

registerIntegrationSetup({
    kind: 'email',
    menuItem: () => ({
        label: 'Configure new email sender domain',
        to: urls.workflows('channels'),
    }),
})

registerIntegrationSetup({
    kind: 'twilio',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Twilio account',
        onClick: () => openModal('twilio'),
    }),
    SetupModal: ({ isOpen, integration, onComplete, onClose }) => (
        <ChannelSetupModal
            isOpen={isOpen}
            channelType="twilio"
            integration={integration}
            onClose={onClose}
            onComplete={onComplete}
        />
    ),
})

registerIntegrationSetup({
    kind: 'databricks',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Databricks account',
        onClick: () => openModal('databricks'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <DatabricksSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})

registerIntegrationSetup({
    kind: 'gitlab',
    menuItem: ({ openModal }) => ({
        label: 'Configure new GitLab account',
        onClick: () => openModal('gitlab'),
    }),
    SetupModal: ({ isOpen, onComplete }) => <GitLabSetupModal isOpen={isOpen} onComplete={onComplete} />,
})

registerIntegrationSetup({
    kind: 'azure-blob',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Azure Blob Storage connection',
        onClick: () => openModal('azure-blob'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <AzureBlobSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})
