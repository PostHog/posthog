import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import * as queryRunner from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, DEFAULT_BI_CONFIG, buildBIQuery, getBIFilterSummary } from './biEditorTypes'
import { BIFilterValueInput } from './BIFilterValueInput'

describe('BI filter value input', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['contains', 'greater_than', 'less_than'] as const)(
        'keeps the %s operand raw despite a saved alias',
        (operator) => {
            const props = { tabId: 'raw-filter-operand' }
            const logic = biEditorLogic(props)
            const unmount = logic.mount()
            const field = {
                id: 'amount',
                name: 'amount',
                expression: 'amount',
                type: operator === 'contains' ? ('string' as const) : ('integer' as const),
                source: { table: 'orders' },
            }
            logic.actions.setAutoUpdate(false)
            logic.actions.restoreState({
                editorView: BIEditorView.BI,
                config: {
                    ...DEFAULT_BI_CONFIG,
                    source: field.source,
                    filters: [{ field, operator, value: '10' }],
                    memberAliases: [{ field, aliases: [{ value: '10', label: 'Ten' }] }],
                },
            })
            render(
                <BindLogic logic={biEditorLogic} props={props}>
                    <BIFilterValueInput index={0} />
                </BindLogic>
            )
            expect(screen.getByText('10')).toBeTruthy()
            expect(screen.queryByText('Ten')).toBeNull()
            cleanup()
            unmount()
        }
    )

    it.each(['equals', 'not_equals', 'in'] as const)('offers searchable suggestions for %s', async (operator) => {
        jest.spyOn(queryRunner, 'performQuery').mockResolvedValue({ results: [['pending'], ['paid'], ['']] } as never)
        const props = { tabId: 'filter-input-test' }
        const logic = biEditorLogic(props)
        logic.mount()
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: {
                ...DEFAULT_BI_CONFIG,
                source: { table: 'orders' },
                filters: [
                    {
                        field: {
                            id: 'status',
                            name: 'status',
                            expression: 'status',
                            type: 'string',
                            source: { table: 'orders' },
                        },
                        operator,
                        value: '',
                    },
                ],
            },
        })
        render(
            <BindLogic logic={biEditorLogic} props={props}>
                <BIFilterValueInput index={0} />
            </BindLogic>
        )
        await userEvent.click(screen.getByTestId('bi-filter-values'))
        await userEvent.click(await screen.findByText('pending'))
        await waitFor(() =>
            expect(
                operator === 'in' ? logic.values.config.filters[0].values : logic.values.config.filters[0].value
            ).toEqual(operator === 'in' ? ['pending'] : 'pending')
        )
        if (operator !== 'in') {
            const input = screen.getByRole('textbox')
            await userEvent.click(input)
            await userEvent.clear(input)
            await userEvent.tab()
            expect(logic.values.config.filters[0].value).toBe('')
            expect(buildBIQuery(logic.values.config)!.query).not.toContain('AND (status')
            await userEvent.click(input)
            await userEvent.click(await screen.findByText('(empty string)'))
            expect(logic.values.config.filters[0].values).toEqual([''])
            expect(getBIFilterSummary(logic.values.config.filters[0])).toContain('(empty string)')
            expect(buildBIQuery(logic.values.config)!.query).toContain(
                `AND (status ${operator === 'equals' ? '=' : '!='} '')`
            )
            await userEvent.click(input)
            await userEvent.tab()
            expect(logic.values.config.filters[0].values).toEqual([''])
        }
        cleanup()
        logic.unmount()
    })
})
