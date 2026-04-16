import { expectLogic } from 'kea-test-utils'

import { sessionSummaryProgressLogic } from 'scenes/session-recordings/player/player-meta/sessionSummaryProgressLogic'

import { initKeaTests } from '~/test/init'

const SESSION_ID = 'test-session-1'

describe('sessionSummaryProgressLogic', () => {
    let logic: ReturnType<typeof sessionSummaryProgressLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionSummaryProgressLogic()
        logic.mount()
    })

    describe('openBySessionId', () => {
        it('auto-opens on startSummarization', async () => {
            await expectLogic(logic, () => {
                logic.actions.startSummarization(SESSION_ID)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('auto-opens on setSummary with content', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, { segments: [], key_actions: [] } as any)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('persists user setSummaryOpen toggle (close stays closed)', async () => {
            logic.actions.startSummarization(SESSION_ID)
            await expectLogic(logic, () => {
                logic.actions.setSummaryOpen(SESSION_ID, false)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: false }),
            })
        })

        it('re-opens via setSummary after user closed, only if summary is non-null', async () => {
            logic.actions.startSummarization(SESSION_ID)
            logic.actions.setSummaryOpen(SESSION_ID, false)

            // Null summary should not reopen
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, null)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: false }),
            })

            // Non-null summary should reopen
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, { segments: [] } as any)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('tracks open state independently per session', async () => {
            await expectLogic(logic, () => {
                logic.actions.startSummarization('session-a')
                logic.actions.setSummaryOpen('session-b', true)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({
                    'session-a': true,
                    'session-b': true,
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setSummaryOpen('session-a', false)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({
                    'session-a': false,
                    'session-b': true,
                }),
            })
        })
    })
})
