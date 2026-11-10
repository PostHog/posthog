import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { initKeaTests } from '~/test/init'

import { ReloadAll } from './Reload'

describe('ReloadAll', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['quill', true, true],
        ['quill', true, false],
        ['lemon', false, true],
        ['lemon', false, false],
    ])('explains a busy %s button and ignores clicks (flag: %s, iconOnly: %s)', async (_, todayRailNav, iconOnly) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: todayRailNav })
        const collection = dataNodeCollectionLogic({ key: 'reload-test' })
        collection.mount()
        collection.actions.collectionNodeLoadData('tile')

        render(
            <Provider>
                <BindLogic logic={dataNodeCollectionLogic} props={{ key: 'reload-test' }}>
                    <ReloadAll iconOnly={iconOnly} />
                </BindLogic>
            </Provider>
        )

        const button = screen.getByRole('button')
        await expectLogic(collection, async () => {
            await userEvent.click(button)
        }).toNotHaveDispatchedActions(['reloadAll'])
        await userEvent.hover(button)
        expect(await screen.findByText('Loading data. You can reload when it finishes.')).toBeInTheDocument()
    })
})
