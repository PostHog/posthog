import { render } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import { ExceptionStepLoader, exceptionStepRenderer } from './exceptionSteps'

describe('ExceptionStepLoader', () => {
    it('skips malformed steps and keeps valid steps sorted by timestamp', async () => {
        const loader = new ExceptionStepLoader('exception-uuid', {
            $lib: 'web',
            $exception_steps: [
                {
                    $message: 'Second valid step',
                    $timestamp: '2024-07-09T12:00:04.000Z',
                    $level: 'info',
                },
                {
                    bad: 'row',
                },
                {
                    $message: 'First valid step',
                    $timestamp: '2024-07-09T12:00:02.000Z',
                    $type: 'ui.interaction',
                },
                {
                    $message: '',
                    $timestamp: '2024-07-09T12:00:05.000Z',
                },
            ],
        } as any)

        const before = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:06.000Z'), 10)

        expect(before.items.map((item) => item.payload.message)).toEqual(['First valid step', 'Second valid step'])
        expect(before.items.map((item) => item.timestamp.toISOString())).toEqual([
            '2024-07-09T12:00:02.000Z',
            '2024-07-09T12:00:04.000Z',
        ])
    })

    it('supports cursor-based pagination through loadAfter and loadBefore', async () => {
        const loader = new ExceptionStepLoader('exception-uuid', {
            $lib: 'web',
            $exception_steps: [
                {
                    $message: 'Step A',
                    $timestamp: '2024-07-09T12:00:01.000Z',
                },
                {
                    $message: 'Step B',
                    $timestamp: '2024-07-09T12:00:02.000Z',
                },
                {
                    $message: 'Step C',
                    $timestamp: '2024-07-09T12:00:03.000Z',
                },
            ],
        } as any)

        const after = await loader.loadAfter(dayjs.utc('2024-07-09T12:00:01.500Z'), 1)
        const before = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:02.500Z'), 1)

        expect(after.items.map((item) => item.payload.message)).toEqual(['Step B'])
        expect(before.items.map((item) => item.payload.message)).toEqual(['Step B'])
    })

    it('uses $-prefixed internal keys so custom properties can avoid conflicts', async () => {
        const loader = new ExceptionStepLoader('exception-uuid', {
            $lib: 'web',
            $exception_steps: [
                {
                    $message: 'Payment attempted',
                    $timestamp: '2024-07-09T12:00:01.000Z',
                    $type: 'checkout',
                    message: 'custom value',
                    timestamp: 'custom value',
                    type: 'custom value',
                    level: 'custom value',
                    retry_count: 2,
                    provider: 'stripe',
                    cart_total: 12900,
                },
            ],
        } as any)

        const before = await loader.loadBefore(dayjs.utc('2024-07-09T12:00:02.000Z'), 10)
        const item = before.items[0]
        const renderExpanded = exceptionStepRenderer.renderExpanded

        expect(before.items).toHaveLength(1)
        expect(item.payload.message).toBe('Payment attempted')
        expect(item.payload.type).toBe('checkout')
        expect(item.payload.stepProperties).toMatchObject({
            message: 'custom value',
            timestamp: 'custom value',
            type: 'custom value',
            level: 'custom value',
            retry_count: 2,
            provider: 'stripe',
            cart_total: 12900,
        })

        expect(renderExpanded).toBeTruthy()

        const { getByText } = render(renderExpanded!({ item, sessionId: 'session-id' }))

        expect(getByText('provider')).toBeTruthy()
        expect(getByText('stripe')).toBeTruthy()
        expect(getByText('cart_total')).toBeTruthy()
        expect(getByText('12900')).toBeTruthy()
    })
})
