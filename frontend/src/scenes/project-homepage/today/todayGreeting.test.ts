import { greetingFor } from './todayGreeting'

describe('greetingFor', () => {
    test.each([
        ['a Wednesday', new Date(2026, 10, 4, 10), ['It’s Wednesday, my dudes.', 'Lemon, it’s Wednesday.']],
        [
            'a Friday afternoon',
            new Date(2026, 10, 6, 15),
            ['Ladies and gentlemen, the weekend.', 'It’s Friday, Friday.'],
        ],
        ['a Monday morning', new Date(2026, 10, 2, 10), ['We are so back, Ada.']],
        ['a Saturday', new Date(2026, 10, 7, 11), ['Ladies and gentlemen, the weekend.', 'Working the weekend, Ada.']],
        [
            'the small hours',
            new Date(2026, 10, 4, 2),
            ['You’re up late, Ada.', 'Chat, is this real?', 'U should go to sleep.'],
        ],
        ['an early morning', new Date(2026, 10, 4, 7), ['Riiiseee and shiiinee.', 'Good morning, sunshine.']],
    ])('greets %s with a greeting for that day and hour', (_, date, expected) => {
        expect(expected).toContain(greetingFor(date, 'Ada'))
    })

    it('keeps the same greeting within one time band of a day', () => {
        expect(greetingFor(new Date(2026, 10, 3, 18, 59), 'Ada')).toBe(greetingFor(new Date(2026, 10, 3, 9), 'Ada'))
    })
})
