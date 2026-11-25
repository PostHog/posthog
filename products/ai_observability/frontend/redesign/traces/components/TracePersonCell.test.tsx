import { cleanup, render } from '@testing-library/react'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import type { TracePersonApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../../shared/cellLoads'
import { TracePersonCell } from './TracePersonCell'

const PERSON: TracePersonApi = { distinctId: 'ana@example.com', label: 'Ana Example' }

describe('TracePersonCell', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each<[string, TracePersonApi | null, TraceCellStatus, string, string | null]>([
        ['a skeleton while loading', null, 'loading', 'Loading…', null],
        [
            'the initial and label linking to the person',
            PERSON,
            'ready',
            'AAna Example',
            urls.personByDistinctId('ana@example.com'),
        ],
        ['a dash for no person', null, 'ready', '-', null],
        ['a failure mark when it could not load', null, 'error', '', null],
    ])('renders %s', (_name, person, status, shown, personPath) => {
        const { container } = render(<TracePersonCell person={person} status={status} />)

        expect(container.textContent).toBe(shown)
        expect(container.querySelector('a')?.getAttribute('href') ?? null).toEqual(
            personPath === null ? null : expect.stringContaining(personPath)
        )
        expect(!!container.querySelector('[role="img"][aria-label^="Couldn\'t load"]')).toBe(status === 'error')
        expect(container.querySelector('[title]')?.closest('.ph-no-capture') ?? null).toBe(
            person === null ? null : container.querySelector('[data-attr="trace-person-link"]')
        )
    })
})
