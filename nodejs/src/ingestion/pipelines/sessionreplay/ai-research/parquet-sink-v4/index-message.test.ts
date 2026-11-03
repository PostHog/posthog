import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'

import { INDEX_HEADER, WRITE_DAY_HEADER, parseIndexMessage } from './index-message'

describe('parseIndexMessage', () => {
    it.each([
        [
            'names the team and session of a rejected row',
            { team_id: 2, session_id: 'session-1' },
            { teamId: 2, sessionId: 'session-1' },
        ],
        ['leaves out an oversized session ID', { team_id: 2, session_id: 's'.repeat(71) }, { teamId: 2 }],
        ['leaves out identifiers of the wrong type', { team_id: '2', session_id: 1 }, {}],
    ])('%s', (_, row, identity) => {
        const warn = jest.spyOn(logger, 'warn').mockImplementation()
        const message = {
            partition: 0,
            offset: 1,
            value: Buffer.from(JSON.stringify(row)),
            headers: [{ [INDEX_HEADER]: Buffer.from('blocks') }, { [WRITE_DAY_HEADER]: Buffer.from('2026-01-01') }],
        } as unknown as Message

        expect(parseIndexMessage(message)).toBeNull()

        const logged = warn.mock.calls[0][2] as Record<string, unknown>
        expect({ teamId: logged.teamId, sessionId: logged.sessionId }).toEqual({
            teamId: undefined,
            sessionId: undefined,
            ...identity,
        })
        warn.mockRestore()
    })
})
