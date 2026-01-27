import { DateTime } from 'luxon'

import { RecipientTokensService } from './recipient-tokens.service'

describe('RecipientTokensService', () => {
    let service: RecipientTokensService
    let fixedTime: DateTime
    beforeEach(() => {
        service = new RecipientTokensService({ ENCRYPTION_SALT_KEYS: 'test-secret', SITE_URL: 'https://test.com' })
        fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
    })
    it('should generate a valid token', () => {
        const token = service.generatePreferencesToken({ team_id: 1, identifier: 'test@test.com' })
        expect(token).toBeDefined()
        expect(token).toMatchInlineSnapshot(
            `"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoxLCJpZGVudGlmaWVyIjoidGVzdEB0ZXN0LmNvbSIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoxNzM2Mjk0NDAwLCJhdWQiOiJwb3N0aG9nOm1lc3NhZ2luZzpzdWJzY3JpcHRpb25fcHJlZmVyZW5jZXMifQ.qpYA4Yx5lYA2ABEd_lgjn-rSGPgl-gg4PIbH3QXIZ7g"`
        )
    })
    it('should validate a valid token', () => {
        const token = service.generatePreferencesToken({ team_id: 1, identifier: 'test@test.com' })
        const result = service.validatePreferencesToken(token)
        expect(result).toEqual({ valid: true, team_id: 1, identifier: 'test@test.com' })
    })
    it('should not accept a valid token with a different audience', () => {
        const token = service['jwt'].sign({ team_id: 1, identifier: 'test@test.com' }, 'other' as any, {
            expiresIn: '7d',
        })
        const result = service.validatePreferencesToken(token)
        expect(result).toEqual({ valid: false })
    })
    it('should not accept an expired token', () => {
        const token = service.generatePreferencesToken({ team_id: 1, identifier: 'test@test.com' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.plus({ days: 6 }).toMillis())
        const result = service.validatePreferencesToken(token)
        expect(result).toEqual({ valid: true, team_id: 1, identifier: 'test@test.com' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.plus({ days: 8 }).toMillis())
        const result2 = service.validatePreferencesToken(token)
        expect(result2).toEqual({ valid: false })
    })
})
