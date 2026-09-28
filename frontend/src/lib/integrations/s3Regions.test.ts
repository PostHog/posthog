import { AWS_ONLY_REGION_OPTIONS, S3_REGION_OPTIONS } from './s3Regions'

describe('s3Regions', () => {
    it('lists every AWS-only region in the S3-family list with the same label', () => {
        expect(S3_REGION_OPTIONS).toEqual(expect.arrayContaining(AWS_ONLY_REGION_OPTIONS))
    })

    it('has no duplicate region values', () => {
        for (const options of [S3_REGION_OPTIONS, AWS_ONLY_REGION_OPTIONS]) {
            const values = options.map((option) => option.value)
            expect(new Set(values).size).toEqual(values.length)
        }
    })
})
