import { clearAgentSignupGoal, readAgentSignupGoal } from './agentSignupGoal'

function signupLocation(next: string | null): Location {
    const url = new URL('https://us.posthog.com/signup')
    if (next !== null) {
        url.searchParams.set('next', next)
    }
    return url as unknown as Location
}

describe('agent signup goal', () => {
    beforeEach(() => {
        sessionStorage.clear()
    })

    test.each([
        ['an authorize URL with a goal', '/oauth/authorize?client_id=abc&goal=Track%20signups', 'Track signups'],
        ['a full same-origin authorize URL', 'https://us.posthog.com/oauth/authorize/?goal=Fix%20errors', 'Fix errors'],
        ['an authorize URL without a goal', '/oauth/authorize?client_id=abc', null],
        ['a blank goal', '/oauth/authorize?goal=%20%20', null],
        ['a goal on another path', '/project/1?goal=Track%20signups', null],
        ['a goal on another origin', 'https://evil.example/oauth/authorize?goal=Track%20signups', null],
    ])('reads %s', (_, next, expected) => {
        expect(readAgentSignupGoal(signupLocation(next))).toBe(expected)
    })

    it('caps the goal at the serializer limit', () => {
        const goal = 'a'.repeat(1500)
        expect(readAgentSignupGoal(signupLocation(`/oauth/authorize?goal=${goal}`))).toHaveLength(1000)
    })

    it('does not leak an abandoned attempt goal into a different signup attempt', () => {
        readAgentSignupGoal(signupLocation('/oauth/authorize?client_id=abc&goal=Track%20signups'))

        expect(readAgentSignupGoal(signupLocation('/oauth/authorize?client_id=other'))).toBeNull()
        expect(readAgentSignupGoal(signupLocation(null))).toBeNull()
    })

    it('keeps the goal for a page without next until it is cleared', () => {
        readAgentSignupGoal(signupLocation('/oauth/authorize?goal=Track%20signups'))
        expect(readAgentSignupGoal(signupLocation(null))).toBe('Track signups')

        clearAgentSignupGoal()
        expect(readAgentSignupGoal(signupLocation(null))).toBeNull()
    })
})
