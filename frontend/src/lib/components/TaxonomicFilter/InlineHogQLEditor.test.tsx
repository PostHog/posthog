import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { InlineHogQLEditor } from './InlineHogQLEditor'

jest.mock('lib/monaco/CodeEditorInline', () => ({
    CodeEditorInline: ({ value }: { value: string }) => <div data-attr="mock-code-editor">{value}</div>,
}))

jest.mock('scenes/max/MaxTool', () => ({
    __esModule: true,
    default: ({ children, identifier }: { children: React.ReactNode; identifier: string }) => (
        <div data-attr="mock-max-tool" data-identifier={identifier}>
            {children}
        </div>
    ),
}))

describe('InlineHogQLEditor', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderEditor(): void {
        render(
            <Provider>
                <InlineHogQLEditor value="" onChange={jest.fn()} />
            </Provider>
        )
    }

    it('does not wrap the editor in MaxTool when the AI snippet flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.SQL_EXPRESSION_AI_SNIPPET]: false,
        })
        renderEditor()
        expect(screen.queryByTestId('mock-max-tool')).toBeNull()
        expect(screen.getByTestId('mock-code-editor')).toBeInTheDocument()
    })

    it('wraps the editor in MaxTool with write_hogql_expression when the AI snippet flag is on', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SQL_EXPRESSION_AI_SNIPPET], {
            [FEATURE_FLAGS.SQL_EXPRESSION_AI_SNIPPET]: true,
        })
        renderEditor()
        const maxTool = screen.getByTestId('mock-max-tool')
        expect(maxTool).toBeInTheDocument()
        expect(maxTool).toHaveAttribute('data-identifier', 'write_hogql_expression')
        expect(screen.getByTestId('mock-code-editor')).toBeInTheDocument()
    })
})
