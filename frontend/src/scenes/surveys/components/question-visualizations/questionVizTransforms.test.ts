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
    it('clears the filter when the active choice is clicked again', () => {
        expect(resolveChoiceClick('Red', null, 'Red')).toEqual({ upsert: { value: null }, nextArmed: null })
    })

    it('switches to another choice in a single click while a filter is active', () => {
        expect(resolveChoiceClick('Red', null, 'Blue')).toEqual({ upsert: { value: 'Blue' }, nextArmed: null })
    })

    it('confirms the armed choice on the second click', () => {
        expect(resolveChoiceClick(null, 'Blue', 'Blue')).toEqual({ upsert: { value: 'Blue' }, nextArmed: null })
    })

    it('arms a fresh choice without changing filters on the first click', () => {
        expect(resolveChoiceClick(null, null, 'Blue')).toEqual({ upsert: null, nextArmed: 'Blue' })
    })

    it('re-arms a different choice when the armed one is not the clicked one', () => {
        expect(resolveChoiceClick(null, 'Red', 'Blue')).toEqual({ upsert: null, nextArmed: 'Blue' })
    })
})
