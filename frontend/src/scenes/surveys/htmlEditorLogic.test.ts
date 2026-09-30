import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { SurveyQuestionDescriptionContentType } from '~/types'

import { HTMLEditorLogicProps, HTMLEditorTab, htmlEditorLogic } from './htmlEditorLogic'

describe('htmlEditorLogic', () => {
    let logic: ReturnType<typeof htmlEditorLogic.build>
    let onChange: jest.Mock

    // Acts as the parent: a tab change comes back to the logic as new props, the way a re-render does
    function mountEditor(value: string, activeTab: SurveyQuestionDescriptionContentType): void {
        onChange = jest.fn()
        const buildProps = (tab: SurveyQuestionDescriptionContentType): HTMLEditorLogicProps => ({
            editorKey: 'test-editor',
            value,
            activeTab: tab,
            onChange,
            onTabChange: (nextTab) => {
                htmlEditorLogic.build(buildProps(nextTab))
            },
        })
        logic = htmlEditorLogic.build(buildProps(activeTab))
        logic.mount()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SURVEYS_RICH_TEXT_DESCRIPTIONS], {
            [FEATURE_FLAGS.SURVEYS_RICH_TEXT_DESCRIPTIONS]: true,
        })
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    test.each([
        ['rich text for supported HTML', '<strong>Bold</strong>', 'rich'],
        ['HTML for unsupported HTML', '<div>Custom</div>', 'html'],
    ])('opens %s', (_, value, expectedTab) => {
        mountEditor(value, 'html')
        expect(logic.values.shownTab).toEqual(expectedTab)
    })

    test.each<[string, string, SurveyQuestionDescriptionContentType, HTMLEditorTab, string | null]>([
        ['text to rich text converts to HTML', 'a < b\nline', 'text', 'rich', '<p>a &lt; b</p><p>line</p>'],
        ['rich text to text converts to plain text', '<p>a &lt; b</p><p>line</p>', 'html', 'text', 'a < b\nline'],
        ['HTML to text converts to plain text', '<div>Custom <b>HTML</b></div>', 'html', 'text', 'Custom HTML'],
        ['text to HTML converts to HTML', 'a < b', 'text', 'html', 'a &lt; b'],
        ['rich text to HTML keeps the value', '<strong>Bold</strong>', 'html', 'html', null],
    ])('%s', (_, value, activeTab, tab, expectedValue) => {
        mountEditor(value, activeTab)
        logic.actions.selectTab(tab)
        jest.runOnlyPendingTimers()

        expect(logic.values.shownTab).toEqual(tab)
        expect(logic.values.pendingConversion).toBeNull()
        expect(onChange.mock.calls).toEqual(expectedValue === null ? [] : [[expectedValue]])
    })

    it('stays on the HTML tab when an edit makes the HTML supported', () => {
        mountEditor('<div>Custom</div>', 'html')
        htmlEditorLogic.build({ ...logic.props, value: 'Custom' })
        expect(logic.values.shownTab).toEqual('html')
    })
})
