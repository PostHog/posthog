import type { ThreadItem, ToolInvocation } from 'products/posthog_ai/frontend/api/types'

import { selectGenUIGenerationActivity } from './genUIGenerationActivityItems'

function toolInvocation(overrides: Partial<ToolInvocation> = {}): ToolInvocation {
    return {
        contentBlocks: [],
        input: {},
        rawServerName: 'posthog',
        rawToolName: 'exec',
        status: 'in_progress',
        toolCallId: 'tool-1',
        ...overrides,
    }
}

describe('selectGenUIGenerationActivity', () => {
    it('shows the latest agent messages, tools, and progress', () => {
        const threadItems: ThreadItem[] = [
            { id: 'human', type: 'human_message', text: 'Build a globe' },
            { id: 'assistant', type: 'assistant_message', text: 'I am reading the canvas source.', complete: true },
            { id: 'tool', type: 'tool_invocation', toolCallId: 'tool-1' },
            {
                id: 'progress',
                type: 'progress',
                progressSteps: [{ key: 'validate', label: 'Validating the visualization', status: 'in_progress' }],
            },
        ]
        const invocations = new Map([
            ['tool-1', toolInvocation({ title: 'Reading the existing visualization', status: 'completed' })],
        ])

        expect(selectGenUIGenerationActivity(threadItems, invocations, null)).toEqual([
            { active: false, id: 'assistant', text: 'I am reading the canvas source.' },
            { active: false, id: 'tool', text: 'Reading the existing visualization' },
            { active: true, id: 'progress', text: 'Validating the visualization' },
        ])
    })

    it('uses only an exec tool name and does not expose its input', () => {
        const threadItems: ThreadItem[] = [{ id: 'tool', type: 'tool_invocation', toolCallId: 'tool-1' }]
        const invocations = new Map([
            [
                'tool-1',
                toolInvocation({
                    input: { command: 'call canvas-publish-create {"secret":"must-not-render"}' },
                }),
            ],
        ])

        expect(selectGenUIGenerationActivity(threadItems, invocations, null)).toEqual([
            { active: true, id: 'tool', text: 'Running canvas-publish-create' },
        ])
    })

    it('keeps streamed text bounded and prefers its changing tail', () => {
        const text = `Starting the visualization. ${'x'.repeat(300)} current streamed output`
        const threadItems: ThreadItem[] = [{ id: 'assistant', type: 'assistant_message', text }]

        const [activity] = selectGenUIGenerationActivity(threadItems, new Map(), null)

        expect(activity.text).toHaveLength(240)
        expect(activity.text.startsWith('…')).toBe(true)
        expect(activity.text.endsWith('current streamed output')).toBe(true)
    })

    it('deduplicates current progress already present in the thread', () => {
        const threadItems: ThreadItem[] = [
            {
                id: 'progress',
                type: 'progress',
                progressSteps: [{ key: 'build', label: 'Building visualization', status: 'in_progress' }],
            },
        ]

        expect(selectGenUIGenerationActivity(threadItems, new Map(), 'Building visualization')).toEqual([
            { active: true, id: 'current-progress', text: 'Building visualization' },
        ])
    })
})
