import React from 'react'

import { extractTextFromChildren, slugifyHeading } from './LemonMarkdown'

describe('LemonMarkdown utilities', () => {
    describe('slugifyHeading', () => {
        it.each([
            ['Hello World', 'hello-world'],
            ['Introduction', 'introduction'],
            ['My Section Title', 'my-section-title'],
        ])('lowercases and hyphenates "%s" → "%s"', (input, expected) => {
            expect(slugifyHeading(input)).toBe(expected)
        })

        it.each([
            ['Hello, World!', 'hello-world'],
            ['What is PostHog?', 'what-is-posthog'],
            ['React & TypeScript', 'react-typescript'],
            ['React  &  TypeScript', 'react-typescript'],
            ['C++ Programming', 'c-programming'],
            ["It's a trap!", 'its-a-trap'],
        ])('removes non-word, non-space, non-hyphen characters from "%s" → "%s"', (input, expected) => {
            expect(slugifyHeading(input)).toBe(expected)
        })

        it.each([
            ['hello   world', 'hello-world'],
            ['multiple   spaces   here', 'multiple-spaces-here'],
            ['tab\there', 'tab-here'],
        ])('collapses whitespace in "%s" → "%s"', (input, expected) => {
            expect(slugifyHeading(input)).toBe(expected)
        })

        it.each([
            ['hello--world', 'hello-world'],
            ['a---b', 'a-b'],
            ['foo----bar', 'foo-bar'],
        ])('collapses consecutive hyphens in "%s" → "%s"', (input, expected) => {
            expect(slugifyHeading(input)).toBe(expected)
        })

        it.each([
            ['-leading-hyphen', 'leading-hyphen'],
            ['trailing-hyphen-', 'trailing-hyphen'],
            ['-both-', 'both'],
        ])('strips leading and trailing hyphens from "%s" → "%s"', (input, expected) => {
            expect(slugifyHeading(input)).toBe(expected)
        })

        it('returns empty string for empty input', () => {
            expect(slugifyHeading('')).toBe('')
        })

        it('returns empty string for input that is only special characters', () => {
            expect(slugifyHeading('!!!@@@###')).toBe('')
        })

        it('preserves hyphens that are part of the original text', () => {
            expect(slugifyHeading('step-by-step guide')).toBe('step-by-step-guide')
        })

        it('handles text that is already a valid slug', () => {
            expect(slugifyHeading('already-a-slug')).toBe('already-a-slug')
        })

        it('handles numeric text', () => {
            expect(slugifyHeading('Chapter 1')).toBe('chapter-1')
        })
    })

    describe('extractTextFromChildren', () => {
        it('returns string children directly', () => {
            expect(extractTextFromChildren('hello')).toBe('hello')
        })

        it('returns empty string for an empty string', () => {
            expect(extractTextFromChildren('')).toBe('')
        })

        it.each([
            [0, '0'],
            [42, '42'],
            [-7, '-7'],
        ])('converts number %s to string "%s"', (input, expected) => {
            expect(extractTextFromChildren(input)).toBe(expected)
        })

        it.each([
            [null, ''],
            [undefined, ''],
            [true, ''],
            [false, ''],
        ])('returns empty string for non-renderable value %s', (input, expected) => {
            expect(extractTextFromChildren(input as any)).toBe(expected)
        })

        it('concatenates an array of strings', () => {
            expect(extractTextFromChildren(['foo', 'bar', 'baz'])).toBe('foobarbaz')
        })

        it('concatenates a mixed array of strings and numbers', () => {
            expect(extractTextFromChildren(['value: ', 42])).toBe('value: 42')
        })

        it('returns empty string for an empty array', () => {
            expect(extractTextFromChildren([])).toBe('')
        })

        it('extracts text from a React element with a string child', () => {
            const element = React.createElement('span', null, 'inner text')
            expect(extractTextFromChildren(element)).toBe('inner text')
        })

        it('extracts text from a nested React element', () => {
            const inner = React.createElement('em', null, 'nested')
            const outer = React.createElement('strong', null, inner)
            expect(extractTextFromChildren(outer)).toBe('nested')
        })

        it('extracts text from an element whose children is an array', () => {
            const element = React.createElement('p', null, 'hello ', 'world')
            expect(extractTextFromChildren(element)).toBe('hello world')
        })

        it('concatenates text across an array of React elements and strings', () => {
            const em = React.createElement('em', null, 'italic')
            const children = ['plain ', em, ' text']
            expect(extractTextFromChildren(children)).toBe('plain italic text')
        })

        it('handles deeply nested React elements', () => {
            const deepest = React.createElement('code', null, 'deep')
            const mid = React.createElement('span', null, deepest)
            const top = React.createElement('div', null, mid)
            expect(extractTextFromChildren(top)).toBe('deep')
        })
    })
})
