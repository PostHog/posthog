import { runInNewContext } from 'node:vm'

import { snippetFunctions } from '@posthog/shared-onboarding/product-analytics'

type SnippetConfig = { api_host: string }
type InitQueueEntry = [token: string, config: SnippetConfig, name: string]

type SnippetStub = unknown[] & {
    _i: InitQueueEntry[]
    init: (token: string, config: SnippetConfig, name?: string) => void
}

type ScriptElement = {
    async?: boolean
    crossOrigin?: string
    onerror?: () => void
    src?: string
    type?: string
}

describe('JavaScript snippet', () => {
    it('queues every init while loading array.js once and retries after a load failure', () => {
        const insertedScripts: ScriptElement[] = []
        const snippetWindow: { posthog?: SnippetStub } = {}
        const snippetDocument = {
            createElement: (): ScriptElement => ({}),
            getElementsByTagName: () => [
                {
                    parentNode: {
                        insertBefore: (script: ScriptElement): void => {
                            insertedScripts.push(script)
                        },
                    },
                },
            ],
        }

        runInNewContext(snippetFunctions(['capture']), { document: snippetDocument, window: snippetWindow })

        const posthog = snippetWindow.posthog
        expect(posthog).not.toBeUndefined()
        if (!posthog) {
            return
        }

        const config = { api_host: 'https://us.i.posthog.com' }
        posthog.init('phc_first', config)
        posthog.init('phc_second', config, 'project2')

        expect(insertedScripts).toHaveLength(1)
        expect(posthog._i).toHaveLength(2)
        expect(posthog._i[0][0]).toBe('phc_first')
        expect(posthog._i[1][0]).toBe('phc_second')
        expect(posthog._i[1][2]).toBe('project2')

        insertedScripts[0].onerror?.()
        posthog.init('phc_third', config, 'project3')

        expect(insertedScripts).toHaveLength(2)
        expect(posthog._i).toHaveLength(3)
    })
})
