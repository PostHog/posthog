import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { OverviewChecksStatus } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'

describe('ModelsOverviewEmptyState', () => {
    let priorAppContext: AppContext | undefined

    function setWarehouseAccess(level: AccessControlLevel): void {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.WarehouseObjects]: level,
            },
        } as AppContext
    }

    beforeEach(() => {
        initKeaTests()
        priorAppContext = window.POSTHOG_APP_CONTEXT
        setWarehouseAccess(AccessControlLevel.Editor)
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it('invites the first view and sends each action to the surface it names', () => {
        render(<ModelsOverviewEmptyState checksStatus="all-passed" />)

        expect(screen.getByText('Create your first view')).toBeTruthy()
        expect(screen.getByTestId('models-overview-create-view').getAttribute('href')).toContain('source=view')
        expect(screen.getByTestId('models-overview-checks').getAttribute('href')).toContain('tab=data-quality')
    })

    it.each([
        ['none' as const, 'Set up checks'],
        ['all-passed' as const, 'View checks'],
        ['some-not-passed' as const, 'View checks'],
    ])('offers %s checks as %s', (checksStatus: OverviewChecksStatus, label: string) => {
        render(<ModelsOverviewEmptyState checksStatus={checksStatus} />)

        expect(screen.queryByTestId('models-overview-checks')?.textContent).toEqual(label)
    })

    it.each([
        [AccessControlLevel.Editor, false],
        [AccessControlLevel.Viewer, true],
    ])('renders create view for a %s as disabled=%s', (level: AccessControlLevel, disabled: boolean) => {
        setWarehouseAccess(level)

        render(<ModelsOverviewEmptyState checksStatus="none" />)

        expect(screen.getByTestId('models-overview-create-view').getAttribute('aria-disabled') === 'true').toBe(
            disabled
        )
    })
})
