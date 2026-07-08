import { createVersionChecker, parseVersion } from './semver'

describe('semver', () => {
    describe('parseVersion', () => {
        it('should parse versions', () => {
            expect(parseVersion('1.0.0')).toEqual({ major: 1, minor: 0, patch: 0 })
            expect(parseVersion('1.0')).toEqual({ major: 1, minor: 0 })
            expect(parseVersion('1')).toEqual({ major: 1 })
            expect(parseVersion('2.444.666666')).toEqual({ major: 2, minor: 444, patch: 666666 })
            expect(parseVersion('1.0.0-alpha')).toEqual({ major: 1, minor: 0, patch: 0, extra: 'alpha' })
            expect(parseVersion('1.0-alpha')).toEqual({ major: 1, minor: 0, extra: 'alpha' })
            expect(parseVersion('1-alpha')).toEqual({ major: 1, extra: 'alpha' })
            expect(() => parseVersion('foo')).toThrow()
            expect(() => parseVersion('0xff')).toThrow()
            expect(() => parseVersion('1.2.three')).toThrow()
            expect(parseVersion('v1.0.0')).toEqual({ major: 1, minor: 0, patch: 0 })
        })
    })

    describe('createVersionChecker', () => {
        it('should create a version checker that checks that a version is above or equal to a specified version', () => {
            const isSupportedVersion = createVersionChecker('4.5.6')
            expect(isSupportedVersion('1.2.3')).toEqual(false)
            expect(isSupportedVersion('4.5.6')).toEqual(true)
            expect(isSupportedVersion('4.5.7')).toEqual(true)
            expect(isSupportedVersion('7.8.9')).toEqual(true)
            expect(isSupportedVersion('4.5.6-alpha')).toEqual(false)
        })
    })
})
