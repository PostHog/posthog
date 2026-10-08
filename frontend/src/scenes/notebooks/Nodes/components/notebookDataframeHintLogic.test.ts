import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { NOTEBOOK_DATAFRAME_HINT_SEEN_KEY, notebookDataframeHintLogic } from './notebookDataframeHintLogic'

describe('notebookDataframeHintLogic', () => {
    let logic: ReturnType<typeof notebookDataframeHintLogic.build>

    const loadUser = (hasSeenProductIntroFor: Record<string, boolean>): void => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            has_seen_product_intro_for: hasSeenProductIntroFor,
        } as UserType)
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS], {
            [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS]: true,
        })
        userLogic.mount()
        logic = notebookDataframeHintLogic({ shortId: 'abc123' })
        logic.mount()
    })

    it('opens against the cell that just finished', async () => {
        loadUser({})

        await expectLogic(logic, () => {
            logic.actions.reportRunFinished('node-1', false)
        }).toMatchValues({ hintNodeId: 'node-1' })
    })

    it.each([
        ['the cell already names its output', { hasReturnVariable: true, seen: {} }],
        [
            'the user dismissed it before',
            { hasReturnVariable: false, seen: { [NOTEBOOK_DATAFRAME_HINT_SEEN_KEY]: true } },
        ],
    ])('stays closed when %s', async (_label, { hasReturnVariable, seen }) => {
        loadUser(seen)

        await expectLogic(logic, () => {
            logic.actions.reportRunFinished('node-1', hasReturnVariable)
        }).toMatchValues({ hintNodeId: null })
    })

    it('stays closed until the user has loaded', async () => {
        userLogic.actions.loadUserSuccess(null)

        await expectLogic(logic, () => {
            logic.actions.reportRunFinished('node-1', false)
        }).toMatchValues({ hintNodeId: null })
    })

    it('keeps the hint on the first cell when a chain finishes several', async () => {
        loadUser({})

        await expectLogic(logic, () => {
            logic.actions.reportRunFinished('node-1', false)
            logic.actions.reportRunFinished('node-2', false)
        }).toMatchValues({ hintNodeId: 'node-1' })
    })

    it('records the dismissal against the user, not the browser', async () => {
        loadUser({})
        logic.actions.reportRunFinished('node-1', false)

        await expectLogic(logic, () => {
            logic.actions.dismissHint()
        })
            .toDispatchActions([
                userLogic.actionCreators.updateHasSeenProductIntroFor(NOTEBOOK_DATAFRAME_HINT_SEEN_KEY),
            ])
            .toMatchValues({ hintNodeId: null })
    })
})
