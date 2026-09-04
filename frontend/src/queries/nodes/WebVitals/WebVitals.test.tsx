import { render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { WebVitalsContent } from './WebVitalsContent'
import { WebVitalsTab } from './WebVitalsTab'

describe('web vitals failure states', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['a failed query', 'Query exceeded the memory limit', "Couldn't load"],
        ['an empty range', null, 'No data for this range'],
    ])('a tile with no value reports %s', (_name, error, expected) => {
        render(<WebVitalsTab metric="INP" value={undefined} isActive={false} isLoading={false} errorMessage={error} />)

        expect(screen.getByText(expected)).toBeTruthy()
    })

    it('the grade panel reports a failed query instead of an empty range', () => {
        render(
            <WebVitalsContent
                webVitalsQueryResponse={undefined}
                isLoading={false}
                error={{ title: 'Query exceeded the memory limit' }}
            />
        )

        expect(screen.queryByText('No data for the selected date range')).toBeNull()
        expect(screen.getByTestId('insight-empty-state')).toBeTruthy()
    })
})
