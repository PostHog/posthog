import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { phaiAiComposerSeedLogic } from './phaiAiComposerSeedLogic'

describe('phaiAiComposerSeedLogic', () => {
    let logic: ReturnType<typeof phaiAiComposerSeedLogic.build>
    let seedLogic: ReturnType<typeof composerSeedLogic.build>

    afterEach(() => {
        logic?.unmount()
        seedLogic?.unmount()
    })

    // `ask` is URL-controlled: without the org-level AI data-processing consent gate a shared link would
    // create and run a task on open — the same gate the legacy `askMax` path and the side-panel bridge apply.
    test.each([
        { consent: true, autoSubmit: true },
        { consent: false, autoSubmit: false },
    ])(
        'forwards the /ai ask query as a seed with autoSubmit=$autoSubmit when consent is $consent',
        ({ consent, autoSubmit }) => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: consent,
            })
            seedLogic = composerSeedLogic()
            seedLogic.mount()

            router.actions.push(urls.ai(undefined, 'Explain this dashboard'))

            logic = phaiAiComposerSeedLogic()
            logic.mount()

            expect(seedLogic.values.seed).toEqual({
                prompt: 'Explain this dashboard',
                autoSubmit,
            })
        }
    )
})
