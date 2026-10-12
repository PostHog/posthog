import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { hogFunctionActivityDescriber } from './activityDescriptions'

describe('hogFunctionActivityDescriber', () => {
    it.each<{
        name: string
        changes: Partial<ActivityChange>[]
        summary: string
        notification: string
    }>([
        {
            name: 'coalesces masked draft fields',
            changes: [
                { field: 'draft', before: 'masked', after: 'masked' },
                { field: 'draft_encrypted_inputs', before: 'masked', after: 'masked' },
            ],
            summary: 'changed the staged changes',
            notification: 'A user changed the staged changes on the hog function: Example destination',
        },
        {
            name: 'describes only changed inputs',
            changes: [
                {
                    field: 'inputs',
                    before: { region: { value: 'west' }, format: { value: 'json' } },
                    after: { region: { value: 'east' }, format: { value: 'json' } },
                },
            ],
            summary: 'updated input: region',
            notification: 'A user updated the input region for the hog function: Example destination',
        },
        {
            name: 'names the changed keys of masked inputs and skips the compiled code',
            changes: [
                {
                    field: 'inputs',
                    before: { region: 'masked', format: 'masked' },
                    after: { region: 'changed', format: 'masked' },
                },
                { field: 'transpiled', before: 'masked', after: 'masked' },
            ],
            summary: 'updated input: region',
            notification: 'A user updated the input region for the hog function: Example destination',
        },
        {
            name: 'describes masked inputs and mappings without values',
            changes: [
                { field: 'inputs', before: 'masked', after: 'masked' },
                { field: 'mappings', before: 'masked', after: 'masked' },
            ],
            summary: 'updated inputs, and updated mappings',
            notification: 'A user updated the hog function: Example destinationupdated inputsupdated mappings',
        },
        {
            name: 'retains source-code links and multi-change notifications',
            changes: [
                { field: 'hog', before: 'return 1', after: 'return 2' },
                { field: 'enabled', before: false, after: true },
            ],
            summary: 'updated source code, and enabled the hog function',
            notification:
                'A user updated the hog function: Example destinationupdated source codeenabled the hog function',
        },
    ])('$name', ({ changes, summary, notification }) => {
        const logItem: ActivityLogItem = {
            activity: 'updated',
            scope: ActivityScope.HOG_FUNCTION,
            created_at: '2026-01-01T00:00:00Z',
            detail: {
                name: 'Example destination',
                merge: null,
                trigger: null,
                changes: changes.map((change) => ({ type: ActivityScope.HOG_FUNCTION, action: 'changed', ...change })),
            },
        }
        const result = hogFunctionActivityDescriber(logItem)
        const text = (element: React.ReactNode): string =>
            (render(<>{element}</>).container.textContent || '').replace(/\s+/g, ' ').trim()

        expect(text(result.summary?.action)).toBe(summary)
        expect(text(result.description)).toBe(notification)
    })
})
