import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { emptyPaginated } from '~/test/mocks/taxonomicFilterApiMock'

import { TaxonomicFilterHeadless } from '../headless'
import { __clearTaxonomicResourceCache } from '../hooks/useTaxonomicResource'
import { taxonomicFilterPinnedPropertiesLogic } from '../taxonomicFilterPinnedPropertiesLogic'
import { TaxonomicFilterGroupType } from '../types'
import { TaxonomicFilterMenu } from './TaxonomicFilterMenu'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn() },
}))

jest.mock('lib/api', () => require('~/test/mocks/taxonomicFilterApiMock').buildTaxonomicFilterApiMock())

const apiGet = jest.requireMock('lib/api').default.get as jest.MockedFunction<any>

// Two content groups, so the picker does not take the sole-group path that
// promotes pinned items into the single list.
const GROUP_TYPES = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.EventProperties]

function renderMenu(): ReturnType<typeof render> {
    return render(
        <Provider>
            <TaxonomicFilterHeadless.Root taxonomicGroupTypes={GROUP_TYPES} onChange={jest.fn()}>
                <TaxonomicFilterMenu />
            </TaxonomicFilterHeadless.Root>
        </Provider>
    )
}

function pinnedRowTexts(): string[] {
    return Array.from(document.querySelectorAll('[data-slot="taxonomic-filter-menu-row"]')).map(
        (el) => el.textContent ?? ''
    )
}

describe('TaxonomicFilterMenu pinned rows', () => {
    beforeEach(() => {
        __clearTaxonomicResourceCache()
        apiGet.mockReset()
        apiGet.mockImplementation(emptyPaginated)
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({})
        localStorage.clear()
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => cleanup())

    // Pins are stored globally, so a pin can outlive the picker it was made in.
    // Without the context filter the cohort still renders: resolveShortcutGroup
    // falls back to the first non-meta group, so it appears as an Events row and
    // commits a cohort id under the Events group.
    it('leaves out a pin whose source group this picker does not offer', async () => {
        const pinnedLogic = taxonomicFilterPinnedPropertiesLogic.build()
        pinnedLogic.mount()
        pinnedLogic.actions.setPinnedFilters([
            {
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: 'signed up',
                item: { name: 'signed up' },
                timestamp: 0,
            },
            {
                groupType: TaxonomicFilterGroupType.Cohorts,
                groupName: 'Cohorts',
                value: 1,
                item: { name: 'Power users' },
                timestamp: 0,
            },
        ])

        renderMenu()

        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-trigger'))
        await waitFor(() => {
            expect(screen.getByText('Pinned')).toBeInTheDocument()
        })
        await userEvent.click(screen.getByText('Pinned'))

        await waitFor(() => {
            expect(pinnedRowTexts().length).toBeGreaterThan(0)
        })
        const rows = pinnedRowTexts()
        expect(rows.some((text) => text.includes('signed up'))).toBe(true)
        expect(rows.some((text) => text.includes('Power users'))).toBe(false)
    })
})
