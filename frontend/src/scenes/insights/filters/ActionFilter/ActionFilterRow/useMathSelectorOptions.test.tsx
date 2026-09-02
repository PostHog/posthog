import { MOCK_DEFAULT_ORGANIZATION, MOCK_GROUP_TYPES } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { apiValueToMathType } from 'scenes/trends/mathsLogic'

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

function OptionValues({ math, mathGroupTypeIndex }: { math: string; mathGroupTypeIndex: number }): JSX.Element {
    const [section] = useMathSelectorOptions({
        math,
        index: 0,
        mathAvailability: MathAvailability.All,
        onMathSelect: jest.fn(),
        trendsDisplayCategory: null,
        mathGroupTypeIndex,
    })
    const values = ('options' in section ? section.options : [])
        .filter((o): o is typeof o & { value: string } => 'value' in o)
        .map((o) => o.value)
    return <div data-attr="option-values">{values.join(' ')}</div>
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
        [BaseMathType.FirstTimeForUser, 'first_time_for_group'],
        [BaseMathType.FirstMatchingEventForUser, 'first_matching_event_for_group'],
    ])('scoping %s to a group emits the group-indexed math type', async (mathType, groupMath) => {
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

        await userEvent.click(selectButton)
        await userEvent.click(await screen.findByText('organizations'))
        expect(onMathSelect).toHaveBeenCalledWith(0, `${groupMath}::0`)
    })

    // MathSelector sets its value from apiValueToMathType, so that value has to exist among the
    // options or a saved series reopens with nothing selected.
    it.each(['first_time_for_group', 'first_matching_event_for_group'])(
        'offers an option matching a saved %s series',
        async (groupMath) => {
            render(
                <Provider>
                    <OptionValues math={groupMath} mathGroupTypeIndex={0} />
                </Provider>
            )

            await waitFor(() => {
                expect(screen.getByTestId('option-values')).toHaveTextContent(apiValueToMathType(groupMath, 0))
            })
        }
    )

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
