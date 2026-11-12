import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { TraceHeader } from './TraceHeader'

describe('TraceHeader', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([null, ''])('names a trace whose name is %p an untitled trace', (name) => {
        render(<TraceHeader name={name} hasError={false} backLink={null} />)

        expect(screen.getByText('Untitled trace')).toBeTruthy()
    })
})
