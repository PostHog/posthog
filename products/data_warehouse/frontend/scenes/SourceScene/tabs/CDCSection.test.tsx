import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { CDCSection } from './CDCSection'
import { sourceSettingsLogic } from './sourceSettingsLogic'

jest.mock('lib/api')

const HEADING = 'Change data capture (CDC)'
const DIRECT_QUERY_COPY = /CDC is only available for sources that sync to the warehouse/

function renderSection(source: ExternalDataSource): ReturnType<typeof render> {
    return render(
        <BindLogic logic={sourceSettingsLogic} props={{ id: 'source-id' }}>
            <CDCSection source={source} />
        </BindLogic>
    )
}

function makeSource(overrides: Partial<ExternalDataSource> = {}): ExternalDataSource {
    return {
        id: 'source-id',
        source_type: 'Supabase',
        access_method: 'warehouse',
        job_inputs: {},
        schemas: [],
        ...overrides,
    } as ExternalDataSource
}

describe('CDCSection', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_CDC], {
            [FEATURE_FLAGS.DWH_POSTGRES_CDC]: true,
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('offers CDC on a Supabase source that syncs to the warehouse', () => {
        renderSection(makeSource())

        expect(screen.getByText(HEADING)).toBeInTheDocument()
        expect(screen.queryByText('Alpha')).not.toBeInTheDocument()
        expect(screen.queryByText(DIRECT_QUERY_COPY)).not.toBeInTheDocument()
    })

    it('explains why CDC is unavailable on a direct query source instead of rendering nothing', () => {
        renderSection(makeSource({ access_method: 'direct' }))

        expect(screen.getByText(HEADING)).toBeInTheDocument()
        expect(screen.getByText(DIRECT_QUERY_COPY)).toBeInTheDocument()
    })

    it('renders nothing for a source type that cannot do CDC', () => {
        const { container } = renderSection(makeSource({ source_type: 'Stripe' }))

        expect(container).toBeEmptyDOMElement()
    })
})
