import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { HogLanguage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { CodeEditorLogicProps, codeEditorLogic } from './codeEditorLogic'

jest.mock('monaco-editor', () => ({ MarkerSeverity: { Error: 8, Warning: 4, Hint: 1 } }))

describe('codeEditorLogic', () => {
    afterEach(() => jest.restoreAllMocks())

    it.each(['success', 'failure'])('keeps metadata private while editing on %s', async (outcome) => {
        initKeaTests()
        const capture = jest.spyOn(posthog, 'capture')
        const captureException = jest.spyOn(posthog, 'captureException')
        const requests: unknown[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    requests.push(((await request.json()) as Record<string, unknown>).query)
                    return outcome === 'success'
                        ? { isValid: true, errors: [], warnings: [], notices: [] }
                        : [400, { detail: 'Could not validate example_engagements for example-org' }]
                },
            },
        })
        const query = 'select name from example_engagements where org_id = {account_external_id}'
        const props: CodeEditorLogicProps = {
            key: 'private-account-editor',
            query,
            language: HogLanguage.hogQL,
            globals: { account_external_id: 'example-org' },
            captureQueryTelemetry: false,
            metadataDebounceMs: 0,
            editor: { getModel: () => ({}) } as CodeEditorLogicProps['editor'],
            monaco: { editor: { setModelMarkers: jest.fn() } } as unknown as CodeEditorLogicProps['monaco'],
        }
        const logic = codeEditorLogic(props)
        logic.mount()
        capture.mockClear()
        await expectLogic(logic, () => logic.actions.reloadMetadata()).toFinishAllListeners()
        await expectLogic(logic, () => {
            codeEditorLogic({ ...props, query: `${query} limit 5` })
        }).toFinishAllListeners()

        expect(requests).toEqual([
            expect.objectContaining({ query, globals: props.globals }),
            expect.objectContaining({ query: `${query} limit 5`, globals: props.globals }),
        ])
        expect(capture.mock.calls.filter(([event]) => event === 'query completed' || event === 'query failed')).toEqual(
            []
        )
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example_engagements')
        expect(JSON.stringify(capture.mock.calls)).not.toContain('example-org')
        expect(captureException).not.toHaveBeenCalled()
        logic.unmount()
    })
})
