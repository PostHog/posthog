import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingGitProviderFileLinksResolveGithubRetrieve } from 'products/error_tracking/frontend/generated/api'

import { ErrorTrackingStackFrameRecord } from '../types'
import { framesCodeSourceLogic } from './framesCodeSourceLogic'
import { stackFrameLogic } from './stackFrameLogic'

jest.mock('products/error_tracking/frontend/generated/api', () => ({
    errorTrackingGitProviderFileLinksResolveGithubRetrieve: jest.fn(),
    errorTrackingGitProviderFileLinksResolveGitlabRetrieve: jest.fn(),
}))

const resolveGithub = errorTrackingGitProviderFileLinksResolveGithubRetrieve as jest.Mock

function record(rawId: string, source: string): ErrorTrackingStackFrameRecord {
    return {
        id: rawId,
        raw_id: rawId,
        created_at: '2026-01-01T00:00:00Z',
        resolved: true,
        symbol_set_ref: 'chunk-1',
        context: { before: [], line: { number: 4, line: 'throw new Error()' }, after: [] },
        contents: {
            raw_id: rawId,
            mangled_name: 'run',
            line: 4,
            column: 1,
            source,
            in_app: true,
            resolved_name: 'run',
            lang: 'javascript',
            resolved: true,
            resolve_failure: null,
            module: null,
        },
        release: {
            id: 'release-1',
            version: '1.0.0',
            created_at: '2026-01-01T00:00:00Z',
            metadata: { git: { remote_url: 'https://github.com/acme/shop.git', commit_id: 'abc' } },
        },
    }
}

describe('framesCodeSourceLogic', () => {
    beforeEach(() => {
        initKeaTests()
        resolveGithub.mockResolvedValue({ found: true, url: 'https://github.com/acme/shop/blob/main/src/cart.ts' })
    })

    it('searches code only for frames without a repo path', async () => {
        const logic = framesCodeSourceLogic()
        logic.mount()

        logic.actions.setDirectLinkRawIds({ direct: true, searched: false })
        stackFrameLogic.actions.loadFromRawIdsSuccess({
            direct: record('direct', 'webpack://acme-web/./src/index.tsx'),
            searched: record('searched', 'webpack://acme-web/./src/cart.ts'),
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(resolveGithub).toHaveBeenCalledTimes(1)
        expect(resolveGithub.mock.calls[0][1]).toMatchObject({ file_name: 'cart.ts' })
        expect(logic.values.getSourceDataForFrame('searched')).toEqual({
            provider: 'github',
            url: 'https://github.com/acme/shop/blob/main/src/cart.ts#L4',
        })
        expect(logic.values.getSourceDataForFrame('direct')).toBeNull()
    })
})
