import { dropChunkLoadExceptions } from './loadPostHogJS'

describe('dropChunkLoadExceptions', () => {
    const exceptionEvent = (exceptions: { type?: string; value?: string }[]): any => ({
        event: '$exception',
        properties: { $exception_list: exceptions },
    })

    it.each([
        ['Safari sprite/chunk download failure', exceptionEvent([{ type: 'TypeError', value: 'Load failed' }]), true],
        [
            'Firefox dynamic-import failure',
            exceptionEvent([{ type: 'TypeError', value: 'error loading dynamically imported module: /static/x.js' }]),
            true,
        ],
        ['real application exception', exceptionEvent([{ type: 'TypeError', value: 'x is not a function' }]), false],
        [
            'mix of chunk-load and real exception is kept',
            exceptionEvent([
                { type: 'TypeError', value: 'Load failed' },
                { type: 'TypeError', value: 'x is not a function' },
            ]),
            false,
        ],
        ['exception event with empty list', exceptionEvent([]), false],
    ])('drops %s: %s', (_label, event, shouldDrop) => {
        expect(dropChunkLoadExceptions(event)).toBe(shouldDrop ? null : event)
    })

    it.each([
        ['pageview event', { event: '$pageview', properties: {} }],
        ['null event', null],
    ])('passes through non-exception %s', (_label, event) => {
        expect(dropChunkLoadExceptions(event as any)).toBe(event)
    })
})
