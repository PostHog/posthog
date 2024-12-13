import { createVersionChecker, highestVersion, lowestVersion, parseVersion, versionToString } from './semver'

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

    describe('lowerVersion', () => {
        it('should return the lower version', () => {
            expect(lowestVersion(['1.0.0', '1.0.1', '1.0.2'])).toEqual({ major: 1, minor: 0, patch: 0 })
            expect(lowestVersion(['1.0.0', '1.0', '1'])).toEqual({ major: 1, minor: 0, patch: 0 })
            expect(lowestVersion(['1.10', '1.2'])).toEqual({ major: 1, minor: 2 })
            expect(lowestVersion(['1.2.3', '1.2.3-alpha'])).toEqual({ major: 1, minor: 2, patch: 3, extra: 'alpha' })
            expect(lowestVersion(['1.2.3-alpha1', '1.2.3-alpha2'])).toEqual({
                major: 1,
                minor: 2,
                patch: 3,
                extra: 'alpha1',
            })
        })
    })
    describe('higherVersion', () => {
        it('should return the higher version', () => {
            expect(highestVersion(['1.0.0', '1.0.1', '1.0.2'])).toEqual({ major: 1, minor: 0, patch: 2 })
            expect(highestVersion(['1.0.0', '1.0', '1'])).toEqual({ major: 1 })
            expect(highestVersion(['1.10', '1.2'])).toEqual({ major: 1, minor: 10 })
            expect(highestVersion(['1.2.3', '1.2.3-alpha'])).toEqual({ major: 1, minor: 2, patch: 3 })
            expect(highestVersion(['1.2.3-alpha1', '1.2.3-alpha2'])).toEqual({
                major: 1,
                minor: 2,
                patch: 3,
                extra: 'alpha2',
            })
        })
    })
    describe('versionToString', () => {
        it('should convert version to string', () => {
            expect(versionToString({ major: 1, minor: 2, patch: 3 })).toEqual('1.2.3')
            expect(versionToString({ major: 1, minor: 2 })).toEqual('1.2')
            expect(versionToString({ major: 1 })).toEqual('1')
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
