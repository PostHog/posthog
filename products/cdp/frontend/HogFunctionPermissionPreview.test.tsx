import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import type { PermissionRequestRecord } from 'products/posthog_ai/frontend/api/types'

import { HogFunctionPermissionPreview } from './HogFunctionPermissionPreview'

jest.mock('scenes/hog-functions/configuration/hogFunctionConfigurationLogic', () => ({
    hogFunctionConfigurationLogic: { findAllMounted: jest.fn() },
}))
jest.mock('scenes/hog-functions/configuration/HogFunctionConfiguration', () => {
    throw new Error('Permission previews must not import the product scene')
})
jest.mock('products/posthog_ai/frontend/components/tool/EditDiffRenderer', () => ({
    DiffEditor: ({ diff }: { diff: { oldText: string; newText: string } }) => (
        <div>
            <span>{diff.oldText}</span>
            <span>{diff.newText}</span>
        </div>
    ),
}))

describe('HogFunctionPermissionPreview', () => {
    afterEach(cleanup)

    const request: PermissionRequestRecord = {
        requestId: 'permission-1',
        toolCallId: 'call-1',
        toolName: 'mcp__posthog__exec',
        options: [],
        rawToolCall: {
            toolCallId: 'call-1',
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command: 'call cdp-functions-partial-update {"id":"function-1","name":"Updated destination"}' },
            status: 'pending',
            contentBlocks: [],
        },
    }

    it.each([
        ['no mounted configuration', []],
        ['configuration unavailable', [{ props: { id: 'function-1' }, values: { loaded: true } }]],
        [
            'a configuration still loading',
            [{ props: { id: 'function-1' }, values: { loaded: false, configuration: {} } }],
        ],
        ['an empty configuration', [{ props: { id: 'function-1' }, values: { loaded: true, configuration: {} } }]],
        [
            'a new-function form carrying no id',
            [
                {
                    props: { templateId: 'template-1' },
                    values: { loaded: true, configuration: { name: 'Template default' } },
                },
            ],
        ],
        [
            'different function',
            [
                {
                    props: { id: 'function-2' },
                    values: { loaded: true, configuration: { name: 'Original destination' } },
                },
            ],
        ],
        [
            'no changes',
            [
                {
                    props: { id: 'function-1' },
                    values: { loaded: true, configuration: { name: 'Updated destination' } },
                },
            ],
        ],
    ])('uses evidence for %s without mounting or fetching a scene', (_name, mounted) => {
        jest.mocked(hogFunctionConfigurationLogic.findAllMounted).mockReturnValue(
            mounted as ReturnType<typeof hogFunctionConfigurationLogic.findAllMounted>
        )
        render(<HogFunctionPermissionPreview request={request} fallback={<div>Original evidence</div>} />)
        expect(screen.getByText('Original evidence')).toBeInTheDocument()
    })

    it('uses evidence when the proposal names no function', () => {
        jest.mocked(hogFunctionConfigurationLogic.findAllMounted).mockReturnValue([
            { props: { id: 'function-1' }, values: { loaded: true, configuration: { name: 'Original destination' } } },
        ] as ReturnType<typeof hogFunctionConfigurationLogic.findAllMounted>)
        render(
            <HogFunctionPermissionPreview
                request={{
                    ...request,
                    rawToolCall: {
                        ...request.rawToolCall,
                        input: { command: 'call cdp-functions-partial-update {"name":"Updated destination"}' },
                    },
                }}
                fallback={<div>Original evidence</div>}
            />
        )
        expect(screen.getByText('Original evidence')).toBeInTheDocument()
    })

    it('renders the proposed diff against the matching mounted configuration', async () => {
        jest.mocked(hogFunctionConfigurationLogic.findAllMounted).mockReturnValue([
            { props: { id: 'function-1' }, values: { loaded: true, configuration: { name: 'Original destination' } } },
        ] as ReturnType<typeof hogFunctionConfigurationLogic.findAllMounted>)
        render(<HogFunctionPermissionPreview request={request} fallback={<div>Original evidence</div>} />)
        expect(screen.queryByText('Original evidence')).not.toBeInTheDocument()
        expect(screen.getByText('Name')).toBeInTheDocument()
        expect(await screen.findByText('Original destination')).toBeInTheDocument()
        expect(screen.getByText('Updated destination')).toBeInTheDocument()
    })
})
