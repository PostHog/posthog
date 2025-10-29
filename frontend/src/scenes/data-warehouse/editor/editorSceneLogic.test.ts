import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { editorSceneLogic, EditorSceneLogicProps, renderTableCount } from './editorSceneLogic'

jest.mock('posthog-js')

describe('editorSceneLogic', () => {
    let logic: ReturnType<typeof editorSceneLogic.build>
    const props: EditorSceneLogicProps = { tabId: 'test-tab-id' }

    beforeEach(() => {
        initKeaTests()
        logic = editorSceneLogic(props)
        logic.mount()
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('reducers', () => {
        it('sets wasPanelActive when setWasPanelActive is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.setWasPanelActive(true)
            }).toMatchValues({
                wasPanelActive: true,
            })

            await expectLogic(logic, () => {
                logic.actions.setWasPanelActive(false)
            }).toMatchValues({
                wasPanelActive: false,
            })
        })

        it('sets panelExplicitlyClosed to false by default', () => {
            expect(logic.values.panelExplicitlyClosed).toBe(false)
        })
    })

    describe('listeners', () => {
        it('captures ai_query_prompted event when reportAIQueryPrompted is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.reportAIQueryPrompted()
            }).toFinishAllListeners()

            expect(posthog.capture).toHaveBeenCalledWith('ai_query_prompted')
        })

        it('captures ai_query_accepted event when reportAIQueryAccepted is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.reportAIQueryAccepted()
            }).toFinishAllListeners()

            expect(posthog.capture).toHaveBeenCalledWith('ai_query_accepted')
        })

        it('captures ai_query_rejected event when reportAIQueryRejected is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.reportAIQueryRejected()
            }).toFinishAllListeners()

            expect(posthog.capture).toHaveBeenCalledWith('ai_query_rejected')
        })

        it('captures ai_query_prompt_open event when reportAIQueryPromptOpen is called', async () => {
            await expectLogic(logic, () => {
                logic.actions.reportAIQueryPromptOpen()
            }).toFinishAllListeners()

            expect(posthog.capture).toHaveBeenCalledWith('ai_query_prompt_open')
        })
    })
})

describe('renderTableCount', () => {
    it('returns null when count is undefined', () => {
        expect(renderTableCount(undefined)).toBeNull()
    })

    it('returns null when count is 0', () => {
        expect(renderTableCount(0)).toBeNull()
    })

    it('renders count with compact notation for small numbers', () => {
        const result = renderTableCount(5)
        expect(result).toBeTruthy()
        expect(result?.props.children).toBe('(5)')
    })

    it('renders count with compact notation for thousands', () => {
        const result = renderTableCount(1500)
        expect(result).toBeTruthy()
        expect(result?.props.children).toMatch(/1\.5k|1k/)
    })

    it('renders count with compact notation for millions', () => {
        const result = renderTableCount(2500000)
        expect(result).toBeTruthy()
        expect(result?.props.children).toMatch(/2\.5m|2m/)
    })

    it('renders with correct CSS classes', () => {
        const result = renderTableCount(100)
        expect(result?.props.className).toContain('text-xs')
        expect(result?.props.className).toContain('mr-1')
        expect(result?.props.className).toContain('italic')
    })
})
