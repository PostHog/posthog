import type { SourceFieldConfig } from 'products/data_warehouse/frontend/types'

import { clonePayloadPreservingFiles, findUploadedFiles } from './sourceFieldFiles'

const KEY_FILE_FIELD: SourceFieldConfig = {
    type: 'file-upload',
    name: 'key_file',
    label: 'JSON key file',
    required: false,
    fileFormat: { format: '.json', keys: ['project_id'] },
}

const AUTH_TYPE_FIELD: SourceFieldConfig = {
    type: 'select',
    name: 'auth_type',
    label: 'Authentication type',
    required: true,
    defaultValue: 'service_account',
    options: [
        {
            label: 'Google Cloud service account',
            value: 'service_account',
            fields: [
                {
                    type: 'oauth',
                    name: 'google_cloud_service_account_integration_id',
                    label: 'Google Cloud service account',
                    required: false,
                    kind: 'google-cloud-service-account',
                },
            ],
        },
        { label: 'JSON key file', value: 'key_file', fields: [KEY_FILE_FIELD] },
    ],
}

function makeKeyFile(): File {
    return new File(['{"project_id":"my-project"}'], 'service-account.json', { type: 'application/json' })
}

describe('sourceFieldFiles', () => {
    describe('findUploadedFiles', () => {
        it('finds a file a select option nests under the parent field', () => {
            const keyFile = makeKeyFile()
            const payload = { auth_type: { selection: 'key_file', key_file: [keyFile] } }

            const uploads = findUploadedFiles([AUTH_TYPE_FIELD], payload)

            expect(uploads).toHaveLength(1)
            expect(uploads[0].file).toBe(keyFile)
            expect(uploads[0].container).toBe(payload.auth_type)
        })

        it('finds a file a switch group nests under the parent field', () => {
            const keyFile = makeKeyFile()
            const fields: SourceFieldConfig[] = [
                {
                    type: 'switch-group',
                    name: 'credentials',
                    label: 'Use a key file?',
                    default: false,
                    fields: [KEY_FILE_FIELD],
                },
            ]
            const payload = { credentials: { enabled: true, key_file: [keyFile] } }

            expect(findUploadedFiles(fields, payload)).toEqual([
                { field: KEY_FILE_FIELD, container: payload.credentials, file: keyFile },
            ])
        })

        it.each([[false], ['False']])('skips a file in a switch group disabled with %s', (enabled) => {
            const fields: SourceFieldConfig[] = [
                {
                    type: 'switch-group',
                    name: 'credentials',
                    label: 'Use a key file?',
                    default: false,
                    fields: [KEY_FILE_FIELD],
                },
            ]

            expect(findUploadedFiles(fields, { credentials: { enabled, key_file: [makeKeyFile()] } })).toEqual([])
        })

        it('finds a file at the top of the payload', () => {
            const keyFile = makeKeyFile()

            expect(findUploadedFiles([KEY_FILE_FIELD], { key_file: [keyFile] })).toHaveLength(1)
        })

        it('skips the option the user did not pick', () => {
            const payload = { auth_type: { selection: 'service_account', key_file: [makeKeyFile()] } }

            expect(findUploadedFiles([AUTH_TYPE_FIELD], payload)).toEqual([])
        })

        it.each([
            ['nothing picked', {}],
            ['an earlier upload the form seeded back in', { project_id: 'my-project' }],
        ])('skips a field holding %s', (_, keyFileValue) => {
            const payload = { auth_type: { selection: 'key_file', key_file: keyFileValue } }

            expect(findUploadedFiles([AUTH_TYPE_FIELD], payload)).toEqual([])
        })
    })

    describe('clonePayloadPreservingFiles', () => {
        it('preserves File instances in nested payloads', () => {
            const keyFile = makeKeyFile()
            const payload = {
                key_file: [keyFile],
                config: { use_custom_region: { enabled: true, region: 'us-east1' } },
            }

            const cloned = clonePayloadPreservingFiles(payload) as Record<string, any>

            expect(cloned).not.toBe(payload)
            expect(cloned.config).not.toBe(payload.config)
            expect(cloned.key_file[0]).toBeInstanceOf(File)
            expect(cloned.key_file[0]).toBe(keyFile)
        })
    })
})
