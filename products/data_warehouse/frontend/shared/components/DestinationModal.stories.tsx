import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import type { CreatableDestinationType } from 'products/data_warehouse/frontend/shared/destinations/types'
import { destinationModalLogic } from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { DestinationModal } from './DestinationModal'

// One connection per kind, so every type's picker has something to select.
const INTEGRATIONS = [
    'postgresql',
    'aws-redshift',
    'snowflake',
    'databricks',
    'google-cloud-service-account',
    'aws-s3',
    's3-compatible',
    'azure-blob',
].map((kind, index) => ({
    id: index + 1,
    kind,
    display_name: `${kind} connection`,
    created_at: '2026-09-01T10:00:00Z',
    created_by: null,
    config: {},
}))

const meta: Meta<typeof DestinationModal> = {
    title: 'Data Warehouse/DestinationModal',
    component: DestinationModal,
    parameters: {
        viewMode: 'story',
        testOptions: { snapshotTargetSelector: '.LemonModal' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': { results: INTEGRATIONS },
            },
        }),
    ],
}
export default meta

function OpenModal({ type }: { type: CreatableDestinationType }): JSX.Element {
    const props = { modalKey: `story-${type}`, onSaved: () => {} }
    const { openForCreate, setDestinationType } = useActions(destinationModalLogic(props))

    useEffect(() => {
        openForCreate()
        setDestinationType(type)
    }, [openForCreate, setDestinationType, type])

    return <DestinationModal {...props} />
}

const Template: StoryFn<{ type: CreatableDestinationType }> = ({ type }) => <OpenModal type={type} />

export const Postgres = Template.bind({})
Postgres.args = { type: 'Postgres' }

export const Snowflake = Template.bind({})
Snowflake.args = { type: 'Snowflake' }

export const Databricks = Template.bind({})
Databricks.args = { type: 'Databricks' }

export const BigQuery = Template.bind({})
BigQuery.args = { type: 'BigQuery' }

export const S3 = Template.bind({})
S3.args = { type: 'S3' }

export const AzureBlob = Template.bind({})
AzureBlob.args = { type: 'AzureBlob' }
