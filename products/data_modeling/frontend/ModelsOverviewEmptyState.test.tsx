import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ModelsOverviewChecksStatus, ModelsOverviewEmptyState } from './ModelsOverviewEmptyState'

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

    it('sends each action to the surface it names', () => {
        render(<ModelsOverviewEmptyState variant="healthy" checksStatus="all-passed" />)

        expect(screen.getByTestId('models-overview-create-view').getAttribute('href')).toContain('source=view')
        expect(screen.getByTestId('models-overview-checks').getAttribute('href')).toContain('tab=data-quality')
        expect(screen.getByTestId('models-overview-lineage').getAttribute('href')).toContain('tab=lineage')
    })

    it.each([
        ['disabled' as const, undefined],
        ['none' as const, 'Set up checks'],
        ['all-passed' as const, 'View checks'],
        ['some-not-passed' as const, 'View checks'],
    ])('offers %s checks as %s', (checksStatus: ModelsOverviewChecksStatus, label: string | undefined) => {
        render(<ModelsOverviewEmptyState variant="healthy" checksStatus={checksStatus} />)

        expect(screen.queryByTestId('models-overview-checks')?.textContent).toEqual(label)
    })

    it('drops the lineage action before a project has any models', () => {
        render(<ModelsOverviewEmptyState variant="first-view" checksStatus="none" />)

        expect(screen.getByText('Create your first view')).toBeTruthy()
        expect(screen.queryByTestId('models-overview-lineage')).toBeNull()
    })

    it.each([
        [AccessControlLevel.Editor, 'false'],
        [AccessControlLevel.Viewer, 'true'],
    ])('renders create view for a %s as aria-disabled=%s', (level: AccessControlLevel, expected: string) => {
        setWarehouseAccess(level)

        render(<ModelsOverviewEmptyState variant="healthy" checksStatus="none" />)

        expect(screen.getByTestId('models-overview-create-view').getAttribute('aria-disabled')).toBe(expected)
    })
})
