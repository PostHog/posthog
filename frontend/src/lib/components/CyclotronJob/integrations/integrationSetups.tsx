import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { registerIntegrationSetup } from './integrationSetupRegistry'

const AwsS3SetupModal = lazyWithRetry(() =>
    import('scenes/integrations/aws-s3/AwsS3SetupModal').then((module) => ({ default: module.AwsS3SetupModal }))
)
const AzureBlobSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/azure-blob/AzureBlobSetupModal').then((module) => ({
        default: module.AzureBlobSetupModal,
    }))
)
const DatabricksSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/databricks/DatabricksSetupModal').then((module) => ({
        default: module.DatabricksSetupModal,
    }))
)
const GitLabSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/gitlab/GitLabSetupModal').then((module) => ({ default: module.GitLabSetupModal }))
)
const GoogleCloudServiceAccountSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/google-cloud-service-account/GoogleCloudServiceAccountSetupModal').then((module) => ({
        default: module.GoogleCloudServiceAccountSetupModal,
    }))
)
const PostgreSQLSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/postgresql/PostgreSQLSetupModal').then((module) => ({
        default: module.PostgreSQLSetupModal,
    }))
)
const RedshiftSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/redshift/RedshiftSetupModal').then((module) => ({ default: module.RedshiftSetupModal }))
)
const S3CompatibleSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/s3-compatible/S3CompatibleSetupModal').then((module) => ({
        default: module.S3CompatibleSetupModal,
    }))
)
const SnowflakeSetupModal = lazyWithRetry(() =>
    import('scenes/integrations/snowflake/SnowflakeSetupModal').then((module) => ({
        default: module.SnowflakeSetupModal,
    }))
)
const ChannelSetupModal = lazyWithRetry(() =>
    import('products/workflows/frontend/Channels/ChannelSetupModal').then((module) => ({
        default: module.ChannelSetupModal,
    }))
)

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
    kind: 'postgresql',
    menuItem: ({ openModal }) => ({
        label: 'Configure new PostgreSQL connection',
        onClick: () => openModal('postgresql'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <PostgreSQLSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})

registerIntegrationSetup({
    kind: 'google-cloud-service-account',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Google Cloud service account',
        onClick: () => openModal('google-cloud-service-account'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <GoogleCloudServiceAccountSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
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

registerIntegrationSetup({
    kind: 'aws-s3',
    menuItem: ({ openModal }) => ({
        label: 'Configure new AWS S3 connection',
        onClick: () => openModal('aws-s3'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <AwsS3SetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})

registerIntegrationSetup({
    kind: 'aws-redshift',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Redshift connection',
        onClick: () => openModal('aws-redshift'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <RedshiftSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})

registerIntegrationSetup({
    kind: 's3-compatible',
    menuItem: ({ openModal }) => ({
        label: 'Configure new S3-compatible storage connection',
        onClick: () => openModal('s3-compatible'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <S3CompatibleSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})

registerIntegrationSetup({
    kind: 'snowflake',
    menuItem: ({ openModal }) => ({
        label: 'Configure new Snowflake connection',
        onClick: () => openModal('snowflake'),
    }),
    SetupModal: ({ isOpen, integration, onComplete }) => (
        <SnowflakeSetupModal isOpen={isOpen} integration={integration} onComplete={onComplete} />
    ),
})
