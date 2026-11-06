import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { hogFunctionSecretReentryLogic } from '../hogFunctionSecretReentryLogic'
import { HogFunctionSecretReentryModal } from './HogFunctionSecretReentryModal'

const MOCK_HOG_FUNCTION_ID = '0196b144-1f82-0000-0d0d-a01de54d6750'

const MOCK_HOG_FUNCTION = {
    id: MOCK_HOG_FUNCTION_ID,
    type: 'destination',
    name: 'HTTP Webhook',
    description: '',
    enabled: true,
    deleted: false,
    hog: "fetch(inputs.url, {'headers': inputs.secret_headers, 'body': inputs.api_key});",
    inputs_schema: [
        { key: 'url', type: 'string', label: 'Webhook URL', required: true },
        { key: 'api_key', type: 'string', label: 'API key', secret: true },
        { key: 'headers', type: 'dictionary', label: 'Headers' },
        { key: 'secret_headers', type: 'dictionary', label: 'Secret headers', secret: true },
    ],
    inputs: {
        url: { value: 'https://hooks.example.com/new' },
        api_key: { secret: true },
        secret_headers: { secret: true, value: { Authorization: '********', 'X-Signature': '********' } },
    },
    filters: {},
    template: { id: 'template-webhook', name: 'HTTP Webhook' },
    status: { state: 0, ratings: [], states: [] },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-15T00:00:00Z',
}

const meta: Meta = {
    title: 'Scenes-App/HogFunctions/SecretReentryModal',
    component: HogFunctionSecretReentryModal,
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/hog_functions/${MOCK_HOG_FUNCTION_ID}/`]: MOCK_HOG_FUNCTION,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForSelector: '.LemonModal input[type="password"]', snapshotBrowsers: [] },
    },
}
export default meta

function Template({ inputKey }: { inputKey: string }): JSX.Element {
    const logicProps = { id: MOCK_HOG_FUNCTION_ID }
    const { requireSecretReentry } = useActions(hogFunctionSecretReentryLogic(logicProps))

    useEffect(() => {
        requireSecretReentry(inputKey, 'save')
    }, [requireSecretReentry, inputKey])

    return <HogFunctionSecretReentryModal logicProps={logicProps} />
}

export const SingleValue: StoryFn = () => <Template inputKey="api_key" />

export const DictionaryEntries: StoryFn = () => <Template inputKey="secret_headers" />
