import { act, cleanup, render, screen } from '@testing-library/react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getFilterLabel } from '~/taxonomy/helpers'
import * as taxonomyLoader from '~/taxonomy/loadCoreFilterDefinitions'
import * as taxonomy from '~/taxonomy/taxonomy'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { SidePanelContent } from './SidePanelContent'

function PanelWithLabel(): JSX.Element {
    return <span>{getFilterLabel('$pageview', TaxonomicFilterGroupType.Events)}</span>
}

describe('SidePanelContent', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('waits for the taxonomy before it renders the panel', async () => {
        let loaded = false
        let release: (() => void) | undefined
        jest.spyOn(taxonomy, 'areCoreFilterDefinitionsLoaded').mockImplementation(() => loaded)
        jest.spyOn(taxonomyLoader, 'loadCoreFilterDefinitions').mockImplementation(
            () =>
                new Promise<void>((resolve) => {
                    release = () => {
                        loaded = true
                        resolve()
                    }
                })
        )

        render(<SidePanelContent activeTab={SidePanelTab.Activity} Content={PanelWithLabel} />)
        await act(async () => {})
        expect(screen.queryByText('Pageview')).toBeNull()

        await act(async () => release!())
        expect(screen.queryByText('Pageview')).not.toBeNull()
    })

    it('renders the panel at once when the taxonomy is already loaded', () => {
        const loadSpy = jest.spyOn(taxonomyLoader, 'loadCoreFilterDefinitions')

        render(<SidePanelContent activeTab={SidePanelTab.Activity} Content={PanelWithLabel} />)

        expect(screen.queryByText('Pageview')).not.toBeNull()
        expect(loadSpy).not.toHaveBeenCalled()
    })
})
