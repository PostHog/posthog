import { summarizeBrowserStorage } from './browserStorageSummary'

describe('summarizeBrowserStorage', () => {
    it('groups per-instance keys under one pattern and keeps the latest use', () => {
        const summary = summarizeBrowserStorage(
            [
                ['12_scenes.insightLogic.new-AdHoc.DataVisualizationNode.3.insightFeedback', 'null'],
                ['12_scenes.insightLogic.new-AdHoc.DataVisualizationNode.41.insightFeedback', 'null'],
                ['12__ai-recordings-widget-toolu_01AbCd--.sessionRecordingsPlaylistLogic.filters', '{}'],
                ['ph_replay_fixed_heatmap_6f1c2d3e-0000-4000-8000-123456789abc', '<html></html>'],
            ],
            {
                '12_scenes.insightLogic.new-AdHoc.DataVisualizationNode.3.insightFeedback': 100,
                '12_scenes.insightLogic.new-AdHoc.DataVisualizationNode.41.insightFeedback': 200,
            }
        )

        expect(summary.keyCount).toBe(4)
        expect(
            summary.groups.map(({ pattern, keyCount, lastUsed, persistedByKea }) => [
                pattern,
                keyCount,
                lastUsed,
                persistedByKea,
            ])
        ).toEqual(
            expect.arrayContaining([
                ['*_scenes.insightLogic.new-AdHoc.DataVisualizationNode.*.insightFeedback', 2, 200, true],
                ['*__ai-recordings-widget-*--.sessionRecordingsPlaylistLogic.filters', 1, null, true],
                ['ph_replay_fixed_heatmap_*', 1, null, false],
            ])
        )
    })
})
