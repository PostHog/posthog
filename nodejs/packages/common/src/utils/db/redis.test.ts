import { getRedisHost } from './redis'

describe('getRedisHost', () => {
    it('extracts host from a standard rediss:// URL', () => {
        expect(getRedisHost('rediss://prod-host:6379')).toBe('prod-host:6379')
    })

    it('strips credentials from a URL with embedded password', () => {
        expect(getRedisHost('rediss://:secret@prod-host:6379')).toBe('prod-host:6379')
    })

    it('strips username and password from URL', () => {
        expect(getRedisHost('rediss://user:pass@my-host:6380/0')).toBe('my-host:6380')
    })

    it('handles a plain hostname that is not a valid URL', () => {
        expect(getRedisHost('my-redis-host')).toBe('my-redis-host')
    })

    it('strips credentials from a non-URL string containing @', () => {
        expect(getRedisHost(':password@hostname')).toBe('hostname')
    })

    it('appends port from options when hostname has no port', () => {
        expect(getRedisHost('hostname', { port: 6380 })).toBe('hostname:6380')
    })

    it('does not double-append port if hostname already has one', () => {
        // 'hostname:6379' parses as a URL with protocol 'hostname:' and pathname '6379'
        // so host is empty — falls through to sanitized placeholder
        // Use a non-URL format with @ to test the catch branch properly
        expect(getRedisHost(':pass@host:6379', { port: 6380 })).toBe('host:6379')
    })
})
