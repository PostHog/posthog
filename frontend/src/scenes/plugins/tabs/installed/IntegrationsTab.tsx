import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginsEmptyState } from './sections/PluginsEmptyState'
import { LemonInput } from '../../../../lib/lemon-ui/LemonInput/LemonInput'
import { LemonButton } from '../../../../lib/lemon-ui/LemonButton'
import { useState } from 'react'
import Icon from '@ant-design/icons/lib/components/Icon'
import { urls } from '../../../urls'

const integrations = [
    // Data Warehouse exports
    {
        name: 'S3',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'batchExport',
    },
    {
        name: 'Snowflake',
        description: 'Exports events to a Snowflake database',
        logo: 'https://raw.githubusercontent.com/PostHog/snowflake-export-plugin/main/logo.png',
        type: 'batchExport',
    },
    {
        name: 'Redshift',
        description: 'Exports event data to Redshift tables',
        logo: 'https://raw.githubusercontent.com/PostHog/redshift-plugin/main/logo.png',
        type: 'batchExport',
    },
    {
        name: 'BigQuery',
        description: 'Exports event data to BigQuery tables',
        logo: 'https://raw.githubusercontent.com/PostHog/bigquery-plugin/main/logo.png',
        type: 'batchExport',
    },
    {
        name: 'Google Sheets',
        description: 'Exports event data to Google Sheets',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'batchExport',
    },
    {
        name: 'Postgres',
        description: 'Exports event data to Postgres tables',
        logo: 'https://raw.githubusercontent.com/PostHog/postgres-plugin/main/logo.png',
        type: 'batchExport',
    },

    // CDP
    {
        name: 'Segment',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Customer.io',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Iterable',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Intercom',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Hubspot',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
    },
    {
        name: 'Mailchimp',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/mailchimp-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Klaviyo',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/klaviyo-plugin/main/logo.png',
        type: 'cdp',
    },
    {
        name: 'Salesforce Marketing Cloud',
        description: 'Exports event data to jsonl format as S3 blobs',
        logo: 'https://raw.githubusercontent.com/PostHog/salesforce-marketing-cloud-plugin/main/logo.png',
        type: 'cdp',
    },
]

export function IntegrationsTab(): JSX.Element {
    const { installedPlugins } = useValues(pluginsLogic)
    const [searchString, setSearchString] = useState('')
    const filteredIntegrations = integrations.filter((integration) =>
        integration.name.toLocaleLowerCase().includes(searchString.toLocaleLowerCase())
    )
    const exportIntegrations = filteredIntegrations.filter((integration) => integration.type === 'batchExport')
    const cdpIntegrations = filteredIntegrations.filter((integration) => integration.type === 'cdp')

    if (installedPlugins.length === 0) {
        return <PluginsEmptyState />
    }

    return (
        <div className="available-integrations">
            <div>Use data integrations to get data in and out of PostHog.</div>

            <LemonInput placeholder="Search available integrations" onChange={setSearchString} />

            <div>
                {exportIntegrations.length ? (
                    <>
                        <h1>Exports to Data Warehouse</h1> <Icon type="info-circle" />
                        <div>Periodically export data to your data warehouse for further analysis.</div>
                        <div className="grid grid-cols-6 gap-4">
                            {exportIntegrations.map((integration) => (
                                <div className="option" key={integration.name}>
                                    <img src={integration.logo} />
                                    <div>{integration.name}</div>
                                    <div>{integration.description}</div>
                                    <LemonButton type="secondary" to={urls.createExport('S3')}>
                                        Create export
                                    </LemonButton>
                                </div>
                            ))}
                        </div>
                        <hr />
                    </>
                ) : null}
                <h1>Customer Data Pipeline</h1>
                <div>Use PostHog events to drive e.g. marketing workflows via external platforms.</div>
                <div className="grid grid-cols-4 gap-4">
                    {cdpIntegrations.map((integration) => (
                        <div className="option" key={integration.name}>
                            <img src={integration.logo} />
                            <div>{integration.name}</div>
                            <div>{integration.description}</div>
                            <LemonButton type="secondary">Add destination</LemonButton>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
