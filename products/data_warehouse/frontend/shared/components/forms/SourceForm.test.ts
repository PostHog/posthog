import { shouldHideSourceField } from './sourceFieldVisibility'

describe('shouldHideSourceField', () => {
    it('hides the legacy BigQuery key file field', () => {
        expect(
            shouldHideSourceField('BigQuery', {
                type: 'file-upload',
                name: 'key_file',
                label: 'Google Cloud JSON key file',
                required: false,
                fileFormat: {
                    format: '.json',
                    keys: ['project_id'],
                },
            })
        ).toBe(true)
    })

    it('keeps other fields visible', () => {
        expect(
            shouldHideSourceField('BigQuery', {
                type: 'text',
                name: 'dataset_id',
                label: 'Dataset ID',
                required: true,
                placeholder: '',
                secret: false,
            })
        ).toBe(false)
    })
})
