import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions } from '~/test/mocks'

import { taxonomicMenuPreferenceLogic } from './taxonomicMenuPreferenceLogic'
import { TaxonomicPopover, TaxonomicStringPopover } from './TaxonomicPopover'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicPopover', () => {
    let actionRequestCount: number

    beforeEach(() => {
        actionRequestCount = 0
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/actions/': () => {
                    actionRequestCount++
                    return [200, { results: [], count: 0 }]
                },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        groupsModel.mount()
    })

    afterEach(() => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        taxonomicMenuPreferenceLogic.actions.setUseNewMenu(true)
        cleanup()
    })

    function renderPopover(
        props: Partial<React.ComponentProps<typeof TaxonomicPopover>> = {}
    ): ReturnType<typeof render> & { onChange: jest.Mock } {
        const onChange = jest.fn()
        const result = render(
            <Provider>
                <TaxonomicPopover groupType={TaxonomicFilterGroupType.Events} onChange={onChange} {...props} />
            </Provider>
        )
        return { ...result, onChange }
    }

    it('displays the current value in the button', () => {
        renderPopover({ value: 'pageview' })
        expect(screen.getByText('pageview')).toBeInTheDocument()
    })

    it('loads actions only after an actions picker opens', async () => {
        renderPopover({
            groupType: TaxonomicFilterGroupType.Actions,
            groupTypes: [TaxonomicFilterGroupType.Actions],
        })

        expect(actionRequestCount).toBe(0)

        await userEvent.click(screen.getByText('Please select'))

        await waitFor(() => {
            expect(actionRequestCount).toBe(1)
        })
    })

    it('resets the legacy picker search after closing completely', async () => {
        renderPopover()

        await userEvent.click(screen.getByText('Please select'))
        await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'event1')
        await userEvent.click(document.body)
        await waitFor(() => {
            expect(screen.queryByTestId('taxonomic-filter-searchfield')).not.toBeInTheDocument()
        })
        await userEvent.click(screen.getByText('Please select'))

        expect(screen.getByTestId('taxonomic-filter-searchfield')).toHaveValue('')
    })

    it('opens the rebuilt actions picker', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]: true })
        taxonomicMenuPreferenceLogic.mount()
        taxonomicMenuPreferenceLogic.actions.setUseNewMenu(true)

        renderPopover({
            groupType: TaxonomicFilterGroupType.Actions,
            groupTypes: [TaxonomicFilterGroupType.Actions],
        })

        await userEvent.click(screen.getByTestId('taxonomic-popover-menu-trigger'))
        await userEvent.click(screen.getByTestId('taxonomic-filter-menu-new'))

        await waitFor(() => {
            expect(screen.getByTestId('menu-filter-search')).toBeInTheDocument()
        })
    })

    it('opens dropdown on click and calls onChange with correct args on selection', async () => {
        const { onChange } = renderPopover({ placeholder: 'Select an event' })
        await userEvent.click(screen.getByText('Select an event'))

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByTestId('prop-filter-events-1'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })
        const [value, groupType, item] = onChange.mock.calls[0]
        expect(value).toBe('event1')
        expect(groupType).toBe(TaxonomicFilterGroupType.Events)
        expect(item.name).toBe('event1')
    })

    it('calls onOpen when opening the dropdown', async () => {
        const onOpen = jest.fn()
        renderPopover({ placeholder: 'Select an event', onOpen })

        await userEvent.click(screen.getByText('Select an event'))

        expect(onOpen).toHaveBeenCalledTimes(1)
    })

    it('clear button calls onChange with empty value', async () => {
        const { onChange } = renderPopover({ value: 'pageview', allowClear: true })
        await userEvent.click(screen.getByLabelText('Clear selection'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledWith('', TaxonomicFilterGroupType.Events, null)
        })
    })

    describe('TaxonomicStringPopover', () => {
        function renderStringPopover(
            props: Partial<React.ComponentProps<typeof TaxonomicStringPopover>> = {}
        ): ReturnType<typeof render> & { onChange: jest.Mock } {
            const onChange = jest.fn()
            const result = render(
                <Provider>
                    <TaxonomicStringPopover
                        groupType={TaxonomicFilterGroupType.Events}
                        onChange={onChange}
                        {...props}
                    />
                </Provider>
            )
            return { ...result, onChange }
        }

        it('coerces selected value to string in onChange', async () => {
            const { onChange } = renderStringPopover({ value: '', placeholder: 'Pick event' })
            await userEvent.click(screen.getByText('Pick event'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-events-1'))

            await waitFor(() => {
                expect(onChange).toHaveBeenCalledTimes(1)
            })
            expect(typeof onChange.mock.calls[0][0]).toBe('string')
        })
    })
})
