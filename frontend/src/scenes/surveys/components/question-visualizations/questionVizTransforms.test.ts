import { hexToRGBA } from 'lib/utils'

import { computeBarColors, resolveChoiceClick, resolveRatingClick } from './questionVizTransforms'

const BLUE = '#1D4BFF'
const PINK = '#CD0F74'
const TEAL = '#43827E'

describe('computeBarColors', () => {
    const labels = ['a', 'b', 'c']
    const baseColors = [BLUE, PINK, TEAL]

    it('returns the base colors unchanged when nothing is highlighted', () => {
        expect(computeBarColors(baseColors, labels, null, false)).toEqual(baseColors)
    })

    it('keeps the highlighted bar at full color and dims the rest with the active alpha', () => {
        expect(computeBarColors(baseColors, labels, 'b', true)).toEqual([
            hexToRGBA(BLUE, 0.22),
            PINK,
            hexToRGBA(TEAL, 0.22),
        ])
    })

    it('uses the lighter armed alpha when no filter is active', () => {
        expect(computeBarColors(baseColors, labels, 'a', false)).toEqual([
            BLUE,
            hexToRGBA(PINK, 0.35),
            hexToRGBA(TEAL, 0.35),
        ])
    })

    it('dims every bar when the highlighted label matches none of them', () => {
        expect(computeBarColors(baseColors, labels, 'missing', true)).toEqual([
            hexToRGBA(BLUE, 0.22),
            hexToRGBA(PINK, 0.22),
            hexToRGBA(TEAL, 0.22),
        ])
    })
})

describe('resolveRatingClick', () => {
    it.each([
        { active: null, clicked: '7', expected: '7' },
        { active: '3', clicked: '7', expected: '7' },
        { active: '7', clicked: '7', expected: null },
    ])('active=$active, clicked=$clicked -> $expected', ({ active, clicked, expected }) => {
        expect(resolveRatingClick(active, clicked)).toBe(expected)
    })
})

describe('resolveChoiceClick', () => {
    it.each([
        {
            desc: 'clears the filter when the active choice is clicked again',
            active: 'Red',
            armed: null,
            clicked: 'Red',
            expected: { upsert: { value: null }, nextArmed: null },
        },
        {
            desc: 'switches to another choice in a single click while a filter is active',
            active: 'Red',
            armed: null,
            clicked: 'Blue',
            expected: { upsert: { value: 'Blue' }, nextArmed: null },
        },
        {
            desc: 'confirms the armed choice on the second click',
            active: null,
            armed: 'Blue',
            clicked: 'Blue',
            expected: { upsert: { value: 'Blue' }, nextArmed: null },
        },
        {
            desc: 'arms a fresh choice without changing filters on the first click',
            active: null,
            armed: null,
            clicked: 'Blue',
            expected: { upsert: null, nextArmed: 'Blue' },
        },
        {
            desc: 're-arms a different choice when the armed one is not the clicked one',
            active: null,
            armed: 'Red',
            clicked: 'Blue',
            expected: { upsert: null, nextArmed: 'Blue' },
        },
    ])('$desc', ({ active, armed, clicked, expected }) => {
        expect(resolveChoiceClick(active, armed, clicked)).toEqual(expected)
    })
})
