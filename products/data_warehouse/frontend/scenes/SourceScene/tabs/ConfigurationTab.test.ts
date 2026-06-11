import type { ExternalDataSource } from '~/types'

import { isLegacyGoogleServiceAccountAuthSource } from './ConfigurationTab'

describe('isLegacyGoogleServiceAccountAuthSource', () => {
    it('returns true for BigQuery sources with no key_file and no integration id', () => {
        const source = {
            source_type: 'BigQuery',
            job_inputs: {},
        } as ExternalDataSource

        expect(isLegacyGoogleServiceAccountAuthSource(source)).toBe(true)
    })

    it('returns false when an integration id already exists', () => {
        const source = {
            source_type: 'BigQuery',
            job_inputs: {
                google_cloud_service_account_integration_id: 7,
            },
        } as ExternalDataSource

        expect(isLegacyGoogleServiceAccountAuthSource(source)).toBe(false)
    })

    it('returns false for non-BigQuery sources', () => {
        const source = {
            source_type: 'Postgres',
            job_inputs: {
                google_cloud_service_account_integration_id: 7,
            },
        } as ExternalDataSource

        expect(isLegacyGoogleServiceAccountAuthSource(source)).toBe(false)
    })
})
