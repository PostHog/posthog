import '@testing-library/jest-dom'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions } from '~/test/mocks'

import { TaxonomicPopover, TaxonomicStringPopover } from './TaxonomicPopover'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicPopover', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
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

    it('opens dropdown on click and calls onChange with correct args on selection', async () => {
        const { onChange } = renderPopover({ placeholder: 'Select an event' })
        userEvent.click(screen.getByText('Select an event'))

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
        })

        userEvent.click(screen.getByTestId('prop-filter-events-1'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })
        const [value, groupType, item] = onChange.mock.calls[0]
        expect(value).toBe('event1')
        expect(groupType).toBe(TaxonomicFilterGroupType.Events)
        expect(item.name).toBe('event1')
    })

    it('clear button calls onChange with empty value', async () => {
        const { onChange } = renderPopover({ value: 'pageview', allowClear: true })
        userEvent.click(screen.getByLabelText('Clear selection'))

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
            userEvent.click(screen.getByText('Pick event'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
            })

            userEvent.click(screen.getByTestId('prop-filter-events-1'))

            await waitFor(() => {
                expect(onChange).toHaveBeenCalledTimes(1)
            })
            expect(typeof onChange.mock.calls[0][0]).toBe('string')
        })
    })
})
