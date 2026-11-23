import { cheatCodeCampaignSlug } from './cheatCodeCampaignSlug'

describe('cheatCodeCampaignSlug', () => {
    it.each([
        ['hesoyam', 'hesoyam'],
        ['HESOYAM', 'hesoyam'],
        ['  HeSoYaM ', 'hesoyam'],
        ['LEN-OGQZ2X35HBG', null],
        ['lenny', null],
        ['hesoyam!', null],
        ['', null],
    ])('cheatCodeCampaignSlug(%p) returns %p', (input, expected) => {
        expect(cheatCodeCampaignSlug(input)).toBe(expected)
    })
})
