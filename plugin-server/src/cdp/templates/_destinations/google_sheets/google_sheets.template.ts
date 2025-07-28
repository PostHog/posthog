import { NativeTemplate } from '~/cdp/types'

export const template: NativeTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'native-google-sheets',
    name: 'Google Sheets',
    description: 'Update a Google Sheet with the incoming event data',
    icon_url: '/static/services/google-sheets.svg',
    category: ['Custom'],
    perform: async (request, { payload }) => {
        try {
            const { spreadsheet_id, spreadsheet_name, data_format, fields } = payload
            
            const rowData = Object.values(fields)
            
            const url = `https://sheets.googleapis.com/v4/spreadsheets/${spreadsheet_id}/values/${spreadsheet_name}:append?valueInputOption=${data_format || 'RAW'}`
            
            const response = await request(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${payload.oauth.access_token}`,
                },
                json: {
                    values: [rowData]
                }
            })
            
            if (response.status >= 400) {
                throw new Error(`Google Sheets API error: ${response.status} - ${response.content}`)
            }
            
            return response
        } catch (error) {
            throw new Error(`Failed to write to Google Sheets: ${error.message}`)
        }
    },
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'google-sheets',
            label: 'Google Sheets account',
            requiredScopes: 'https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/userinfo.email',
            secret: false,
            required: true,
        },
        {
            key: 'spreadsheet_id',
            type: 'string', 
            label: 'Spreadsheet ID',
            secret: false,
            required: true,
            description: 'The ID of the Google Sheet to update. In case of https://docs.google.com/spreadsheets/d/17EdJJMxC0ovhCqpSxK4oksVO-MNlL5U0gHn7vqxkXZE/edit?gid=0#gid=0, the ID is `17EdJJMxC0ovhCqpSxK4oksVO-MNlL5U0gHn7vqxkXZE`',
        },
        {
            key: 'spreadsheet_name',
            type: 'string',
            label: 'Spreadsheet Name',
            secret: false,
            required: true,
            description: 'The name of the sheet/tab within the spreadsheet',
            default: 'Sheet1',
        },
        {
            key: 'data_format',
            type: 'choice',
            label: 'Data Format',
            secret: false,
            choices: [
                {
                    label: 'RAW - The values the user has entered will not be parsed and will be stored as-is.',
                    value: 'RAW',
                },
                {
                    label: 'USER_ENTERED - The values will be parsed as if the user typed them into the UI. Numbers will stay as numbers, but strings may be converted to numbers, dates, etc. following the same rules that are applied when entering text into a cell via the Google Sheets UI.',
                    value: 'USER_ENTERED',
                },
            ],
            default: 'RAW',
            required: false,
            description: 'How the input data should be interpreted.',
        },
        {
            key: 'fields',
            type: 'dictionary',
            label: 'Fields',
            secret: false,
            required: true,
            default: {
                timestamp: "{event.timestamp}",
                event_name: "{event.event}",
            },
            description: 'Dictionary defining the fields to be written to the sheet.',
        },
    ],
}
