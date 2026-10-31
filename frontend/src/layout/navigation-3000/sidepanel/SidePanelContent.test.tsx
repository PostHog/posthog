import { act, render, screen } from '@testing-library/react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getFilterLabel } from '~/taxonomy/helpers'
import * as taxonomyLoader from '~/taxonomy/loadCoreFilterDefinitions'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { SidePanelContent } from './SidePanelContent'

function PanelWithLabel(): JSX.Element {
    return <span>{getFilterLabel('$pageview', TaxonomicFilterGroupType.Events)}</span>
}

describe('SidePanelContent', () => {
    it('waits for the taxonomy before it renders the panel', async () => {
        let release: (() => void) | undefined
        const loadSpy = jest.spyOn(taxonomyLoader, 'loadCoreFilterDefinitions').mockImplementation(
            () =>
                new Promise<void>((resolve) => {
                    release = resolve
                })
        )
        initKeaTests()
        try {
            render(<SidePanelContent activeTab={SidePanelTab.Activity} Content={PanelWithLabel} />)
            await act(async () => {})
            expect(screen.queryByText('Pageview')).toBeNull()

            await act(async () => release!())
            expect(screen.queryByText('Pageview')).not.toBeNull()
        } finally {
            loadSpy.mockRestore()
        }
    })
})
