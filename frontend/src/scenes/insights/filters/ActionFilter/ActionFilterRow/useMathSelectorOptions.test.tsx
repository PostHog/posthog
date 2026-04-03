import { MOCK_DEFAULT_ORGANIZATION, MOCK_GROUP_TYPES } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BaseMathType, OrganizationType } from '~/types'

import { MathAvailability } from './types'
import { useMathSelectorOptions } from './useMathSelectorOptions'

function ActiveActorLabel({
    mathType,
    onMathSelect,
}: {
    mathType: BaseMathType
    onMathSelect: jest.Mock
}): JSX.Element {
    const [section] = useMathSelectorOptions({
        math: 'total',
        index: 0,
        mathAvailability: MathAvailability.All,
        onMathSelect,
        trendsDisplayCategory: null,
        mathGroupTypeIndex: undefined,
    })
    const opt = ('options' in section ? section.options : []).find((o) => 'value' in o && o.value === mathType)
    const label = opt && 'labelInMenu' in opt ? opt.labelInMenu : null
    return <div data-attr="actor-label">{label as React.ReactNode}</div>
}

describe('useMathSelectorOptions – active actor select', () => {
    afterEach(cleanup)

    beforeEach(() => {
        const orgWithGroups: OrganizationType = {
            ...MOCK_DEFAULT_ORGANIZATION,
            available_product_features: [
                { key: AvailableFeature.GROUP_ANALYTICS, name: AvailableFeature.GROUP_ANALYTICS },
            ],
        }
        initKeaTests(true, undefined as any, undefined as any, orgWithGroups)
        useMocks({
            get: {
                '/api/projects/:team/groups_types': MOCK_GROUP_TYPES,
            },
        })
        useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])
        groupsModel.mount()
    })

    it.each([
        [BaseMathType.WeeklyActiveUsers, 'weekly_active'],
        [BaseMathType.MonthlyActiveUsers, 'monthly_active'],
    ])('switching %s actor select back to "users" preserves the correct math type', async (mathType, expectedMath) => {
        const onMathSelect = jest.fn()

        render(
            <Provider>
                <ActiveActorLabel mathType={mathType} onMathSelect={onMathSelect} />
            </Provider>
        )

        await waitFor(() => {
            expect(screen.getByTestId('actor-label').querySelector('button')).toBeInTheDocument()
        })

        const selectButton = screen.getByTestId('actor-label').querySelector('button')!

        // Switch to a group first
        await userEvent.click(selectButton)
        await userEvent.click(await screen.findByText('organizations'))
        expect(onMathSelect).toHaveBeenCalledWith(0, `${expectedMath}::0`)
        onMathSelect.mockClear()

        // Switch back to "users"
        await userEvent.click(selectButton)
        await userEvent.click(await screen.findByText('users'))
        expect(onMathSelect).toHaveBeenCalledWith(0, expectedMath)
    })
})
