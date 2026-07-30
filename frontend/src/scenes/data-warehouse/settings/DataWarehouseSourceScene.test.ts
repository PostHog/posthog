import {
    getDefaultDataWarehouseSourceSceneTab,
    isManagedSourceSceneId,
    resolveManagedSourceActiveTab,
    shouldShowManagedSourceMetricsTab,
    shouldShowManagedSourceSyncsTab,
} from 'products/data_warehouse/frontend/scenes/SourceScene/SourceScene'

describe('DataWarehouseSourceScene', () => {
    it('defaults managed source routes to the schemas tab', () => {
        expect(getDefaultDataWarehouseSourceSceneTab('managed-123')).toEqual('schemas')
        expect(getDefaultDataWarehouseSourceSceneTab('019d8b93-b5ba-0000-52e1-99fa41d90d4d')).toEqual('schemas')
    })

    it('defaults self-managed source routes to the configuration tab', () => {
        expect(getDefaultDataWarehouseSourceSceneTab('self-managed-123')).toEqual('configuration')
    })

    it('treats raw source ids as managed source scene ids', () => {
        expect(isManagedSourceSceneId('managed-123')).toEqual(true)
        expect(isManagedSourceSceneId('019d8b93-b5ba-0000-52e1-99fa41d90d4d')).toEqual(true)
        expect(isManagedSourceSceneId('self-managed-123')).toEqual(false)
    })

    it('hides the syncs tab until the source is loaded and for direct query sources', () => {
        expect(shouldShowManagedSourceSyncsTab(null)).toEqual(false)
        expect(shouldShowManagedSourceSyncsTab({ access_method: 'direct' })).toEqual(false)
        expect(shouldShowManagedSourceSyncsTab({ access_method: 'warehouse' })).toEqual(true)
    })

    it.each([
        [null, true, false],
        [{ access_method: 'direct' as const }, true, false],
        [{ access_method: 'warehouse' as const }, true, true],
        [{ access_method: 'warehouse' as const }, false, false],
    ])('hides the metrics tab for direct query sources (source %p, flag %p)', (source, flagEnabled, expected) => {
        expect(shouldShowManagedSourceMetricsTab(source, flagEnabled)).toEqual(expected)
    })

    it.each([
        [['schemas', 'syncs', 'metrics', 'configuration', 'history'], 'metrics' as const, 'metrics'],
        [['schemas', 'configuration', 'history'], 'configuration' as const, 'configuration'],
        // A source-dependent tab is absent whenever the source is missing, including when its
        // request failed and loading has already finished.
        [['schemas', 'configuration', 'history'], 'metrics' as const, 'schemas'],
        [['schemas', 'configuration', 'history'], 'syncs' as const, 'schemas'],
        [['schemas', 'configuration', 'history'], 'webhook' as const, 'schemas'],
    ])('falls back to schemas when the selected tab is not rendered (%p, %p)', (tabKeys, currentTab, expected) => {
        expect(resolveManagedSourceActiveTab(tabKeys, currentTab)).toEqual(expected)
    })
})
