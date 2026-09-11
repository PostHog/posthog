import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { RegexMatchingResult, startRegexMatching } from 'lib/regex/regexMatching'

import { initKeaTests } from '~/test/init'

import { ingestionControlsLogic } from '../ingestionControlsLogic'
import { UrlTriggerConfig } from '../types'
import { UrlConfig } from './UrlConfig'
import { urlConfigLogic } from './urlConfigLogic'
import { UrlRegexPreviewStatus } from './UrlRegexPreviewStatus'

jest.mock('lib/regex/regexMatching', () => ({
    ...jest.requireActual('lib/regex/regexMatching'),
    startRegexMatching: jest.fn(),
}))

describe('URL regex preview status', () => {
    afterEach(cleanup)
    it('distinguishes pending, failures and syntax errors from a completed non-match', () => {
        const { rerender } = render(<UrlRegexPreviewStatus preview={{ status: 'pending' }} />)
        expect(screen.getByText('Checking URL…')).toBeInTheDocument()
        expect(screen.queryByText(/doesn't match/)).not.toBeInTheDocument()
        rerender(<UrlRegexPreviewStatus preview={{ status: 'error', error: 'timeout' }} />)
        expect(screen.getByText(/took too long/)).toBeInTheDocument()
        expect(screen.queryByText(/doesn't match/)).not.toBeInTheDocument()
        rerender(<UrlRegexPreviewStatus preview={{ status: 'success', results: [{ error: 'syntax_error' }] }} />)
        expect(screen.getByText(/invalid regex/)).toBeInTheDocument()
        expect(screen.queryByText(/doesn't match/)).not.toBeInTheDocument()
        rerender(<UrlRegexPreviewStatus preview={{ status: 'success', results: [{ matches: false }] }} />)
        expect(screen.getByText(/doesn't match any patterns/)).toBeInTheDocument()
    })

    it('removes row verdicts immediately when URL config or test input changes', async () => {
        initKeaTests()
        const requests: { resolve: (result: RegexMatchingResult) => void; cancel: jest.Mock }[] = []
        jest.mocked(startRegexMatching).mockImplementation(() => {
            let resolve!: (result: RegexMatchingResult) => void
            const promise = new Promise<RegexMatchingResult>((done) => {
                resolve = done
            })
            const request = { resolve, cancel: jest.fn() }
            requests.push(request)
            return { promise, cancel: request.cancel }
        })
        const onChange = jest.fn()
        const config: UrlTriggerConfig[] = [{ url: 'a', matching: 'regex' }]
        const renderConfig = (patterns: UrlTriggerConfig[], checkUrl: string): JSX.Element => (
            <BindLogic
                logic={ingestionControlsLogic}
                props={{
                    logicKey: 'preview-test',
                    resourceType: 'session_recording',
                    matchType: 'any',
                    onChangeMatchType: onChange,
                }}
            >
                <UrlConfig
                    logic={urlConfigLogic}
                    logicProps={{ logicKey: 'preview-test', initialUrlTriggerConfig: patterns, onChange }}
                    formKey="proposedUrlTrigger"
                    addUrl={onChange}
                    validationWarning={null}
                    title="URL patterns"
                    description="Test URL patterns"
                    checkUrl={checkUrl}
                    setCheckUrl={onChange}
                    isAddFormVisible={false}
                    config={patterns}
                    editIndex={null}
                    isSubmitting={false}
                    onAdd={onChange}
                    onCancel={onChange}
                    onEdit={onChange}
                    onRemove={onChange}
                />
            </BindLogic>
        )
        const { rerender, unmount } = render(renderConfig(config, 'a'))
        expect(screen.getByText('Checking URL…')).toBeInTheDocument()
        await act(async () => {
            requests[0].resolve({ status: 'success', results: [{ matches: true }] })
        })
        expect(screen.getByText('Matches')).toBeInTheDocument()
        rerender(renderConfig([{ url: 'b', matching: 'regex' }], 'a'))
        expect(screen.queryByText('Matches')).not.toBeInTheDocument()
        expect(screen.getByText('Checking URL…')).toBeInTheDocument()
        rerender(renderConfig([{ url: 'b', matching: 'regex' }], '  '))
        expect(screen.queryByText('Checking URL…')).not.toBeInTheDocument()
        expect(screen.queryByText(/doesn't match/)).not.toBeInTheDocument()
        expect(requests[1].cancel).toHaveBeenCalledTimes(1)
        unmount()
    })
})
