import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { TodayChatVisibility, chatVisibility, personalSpace, publicSpace } from './todayChatVisibility'

type Space = Pick<ChannelDTOApi, 'id' | 'channel_type' | 'system_role'>

const SPACES: Space[] = [
    { id: 'mine', channel_type: 'personal', system_role: 'personal' },
    { id: 'team', channel_type: 'public', system_role: 'general' },
    { id: 'design', channel_type: 'public', system_role: null },
    { id: 'perf', channel_type: 'private', system_role: null },
]

describe('todayChatVisibility', () => {
    it.each<[string, string | null, TodayChatVisibility]>([
        ['a chat with no space', null, 'personal'],
        ['the personal space', 'mine', 'personal'],
        ['the team space', 'team', 'public'],
        ['an older public space', 'design', 'public'],
        ['an older private space', 'perf', 'shared'],
        ['a space the person cannot list', 'gone', 'shared'],
    ])('reads %s as %s', (_, spaceId, expected) => {
        expect(chatVisibility(spaceId, SPACES)).toBe(expected)
    })

    it('reads every chat as personal until the spaces load, so no row flashes a shared badge', () => {
        expect(chatVisibility('perf', [])).toBe('personal')
    })

    it('finds the spaces that Make public and Move to personal move a chat to', () => {
        expect(personalSpace(SPACES)?.id).toBe('mine')
        expect(publicSpace(SPACES)?.id).toBe('team')
        expect(publicSpace(SPACES.filter((space) => space.system_role !== 'general'))).toBeNull()
    })
})
