import { ProjectTokenLookup } from './project-token-lookup'

describe('ProjectTokenLookup', () => {
    let tokens: Record<string, number>
    let postgres: any
    let lookup: ProjectTokenLookup

    beforeEach(() => {
        jest.useFakeTimers()
        tokens = { phc_live: 7 }
        postgres = {
            query: jest.fn((_use: unknown, _sql: string, [requested]: [string[]]) =>
                Promise.resolve({
                    rows: requested
                        .filter((token) => token in tokens)
                        .map((token) => ({ id: tokens[token], api_token: token })),
                })
            ),
        }
        lookup = new ProjectTokenLookup(postgres)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const resolve = async (token: string): Promise<unknown> => {
        const pending = lookup.getTeamByToken(token)
        await jest.advanceTimersByTimeAsync(50)
        return await pending
    }

    it('resolves a project token to its team', async () => {
        expect(await resolve('phc_live')).toEqual({ id: 7, api_token: 'phc_live' })
    })

    it('does not resolve a team by its id', async () => {
        expect(await resolve('7')).toBeNull()
    })

    it('refuses a token too long to be a project token without querying or caching it', async () => {
        expect(await resolve('a'.repeat(201))).toBeNull()
        expect(postgres.query).not.toHaveBeenCalled()
    })

    it('stops resolving a reset token within seconds', async () => {
        expect(await resolve('phc_live')).not.toBeNull()
        delete tokens.phc_live

        await jest.advanceTimersByTimeAsync(6_500)

        expect(await resolve('phc_live')).toBeNull()
    })
})
