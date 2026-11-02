import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Suspense, createElement } from 'react'

import { isChunkLoadError } from './isChunkLoadError'
import { lazyWithPreload, retryBootImport, retryImport } from './retryImport'

describe('retryImport', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const chunkError = (): Error => new Error('Failed to fetch dynamically imported module: /x.js')

    it('resolves on the first attempt without retrying', async () => {
        const factory = jest.fn().mockResolvedValue('module')

        await expect(retryImport(factory)).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('resolves a factory that returns a non-promise value', async () => {
        const factory = jest.fn().mockReturnValue('module')

        await expect(retryImport(factory)).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('retries a transient chunk error and resolves', async () => {
        const factory = jest.fn().mockRejectedValueOnce(chunkError()).mockResolvedValue('module')

        const promise = retryImport(factory)
        await jest.runAllTimersAsync()

        await expect(promise).resolves.toBe('module')
        expect(factory).toHaveBeenCalledTimes(2)
    })

    it('exhausts retries on a persistent chunk error and rejects', async () => {
        const factory = jest.fn().mockRejectedValue(chunkError())

        const promise = retryImport(factory)
        void promise.catch(() => {}) // avoid an unhandled rejection while the backoff timers drain
        await jest.runAllTimersAsync()

        await expect(promise).rejects.toThrow('Failed to fetch dynamically imported module')
        expect(factory).toHaveBeenCalledTimes(3)
    })

    it('marks a minified boot module-evaluation TypeError without retrying', async () => {
        const error = new TypeError('g is not a function')
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryBootImport(factory)).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(1)
        expect(isChunkLoadError(error)).toBe(true)
    })

    it('marks a chunk parse SyntaxError without retrying', async () => {
        const error = new SyntaxError('Invalid or unexpected token')
        const factory = jest.fn().mockRejectedValue(error)

        await expect(retryImport(factory)).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(1)
        expect(isChunkLoadError(error)).toBe(true)
    })

    it('rethrows a non-chunk error immediately without retrying', async () => {
        const factory = jest.fn().mockRejectedValue(new TypeError('undefined is not a function'))

        await expect(retryImport(factory)).rejects.toThrow('undefined is not a function')
        expect(factory).toHaveBeenCalledTimes(1)
    })

    it('retries a generic network TypeError and marks it as a chunk load error once exhausted', async () => {
        const error = new TypeError('Load failed')
        const factory = jest.fn().mockRejectedValue(error)

        const promise = retryImport(factory)
        void promise.catch(() => {})
        await jest.runAllTimersAsync()

        await expect(promise).rejects.toBe(error)
        expect(factory).toHaveBeenCalledTimes(3)
        expect(isChunkLoadError(error)).toBe(true)
    })

    describe('lazyWithPreload', () => {
        beforeEach(() => {
            jest.useRealTimers()
        })

        afterEach(() => {
            cleanup()
        })

        const Greeting = ({ name }: { name: string }): JSX.Element => createElement('span', null, `hello ${name}`)

        const renderInSuspense = (Component: (props: { name: string }) => JSX.Element): void => {
            render(
                createElement(
                    Suspense,
                    { fallback: createElement('span', null, 'loading') },
                    createElement(Component, { name: 'max' })
                )
            )
        }

        it.each([
            { preloaded: true, firstPaint: 'hello max' },
            { preloaded: false, firstPaint: 'loading' },
        ])('preloaded=$preloaded shows "$firstPaint" on first paint', async ({ preloaded, firstPaint }) => {
            const factory = jest.fn().mockResolvedValue({ default: Greeting })
            const { Component, preload } = lazyWithPreload(factory)
            if (preloaded) {
                await preload()
            }

            renderInSuspense(Component)

            expect(screen.getByText(firstPaint)).toBeInTheDocument()
            expect(await screen.findByText('hello max')).toBeInTheDocument()
            expect(factory).toHaveBeenCalledTimes(1)
        })

        it('loads again on render after a failed preload', async () => {
            const factory = jest.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue({ default: Greeting })
            const { Component, preload } = lazyWithPreload(factory)
            await preload()

            renderInSuspense(Component)

            expect(await screen.findByText('hello max')).toBeInTheDocument()
            expect(factory).toHaveBeenCalledTimes(2)
        })
    })
})
