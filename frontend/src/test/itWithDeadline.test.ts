import { runNodeWithDeadline } from './itWithDeadline'

describe('runNodeWithDeadline', () => {
    it('returns successful child output', () => {
        expect(runNodeWithDeadline(['-e', 'process.stdout.write("ready")'])).toBe('ready')
    })

    it.each([
        ['nonzero exit', 'process.stderr.write("fixture failure"); process.exit(7)', /status 7.*fixture failure/s],
        ['signal', 'process.kill(process.pid, "SIGTERM")', /signal SIGTERM/],
        ['output overflow', 'process.stdout.write("x".repeat(2 * 1024 * 1024))', /ENOBUFS/],
    ])('rejects %s', (_name, source, error) => {
        expect(() => runNodeWithDeadline(['-e', source])).toThrow(error)
    })

    it('kills a child at the external deadline and can run another child afterwards', () => {
        expect(() => runNodeWithDeadline(['-e', 'setTimeout(() => {}, 10000)'], 100)).toThrow(
            /signal SIGKILL.*ETIMEDOUT/s
        )
        expect(runNodeWithDeadline(['-e', 'process.stdout.write("next")'])).toBe('next')
    })
})
