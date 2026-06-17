import { cleanup, renderHook } from '@testing-library/react'

import { examples } from '~/queries/examples'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { QuerySchema } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { useWebTileExportAdapter } from './webTileHeaderHooks'

const worldMapQuery = examples.WebAnalyticsWorldMap as QuerySchema

describe('useWebTileExportAdapter', () => {
    let collection: ReturnType<typeof dataNodeCollectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        collection = dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID })
        collection.mount()
    })

    afterEach(() => {
        cleanup()
        collection?.unmount()
    })

    const registeredIds = (): string[] => collection.values.mountedDataNodes.map((node) => node.id)

    // Regression: the tile header renders before its chart, so this hook would let insightDataLogic build
    // the shared, key-only dataNodeLogic first without a collection id, dropping the tile from "reload all".
    it('registers the tile data node into the web analytics collection', () => {
        const insightProps: InsightLogicProps = {
            dashboardItemId: 'new-AdHoc.web-analytics-test-tile' as any,
            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
        }

        renderHook(() => useWebTileExportAdapter(worldMapQuery, insightProps))

        expect(registeredIds()).toContain(insightVizDataNodeKey(insightProps))
    })

    it('rebinds to the new node when insightProps change (tab switch)', () => {
        const firstProps: InsightLogicProps = {
            dashboardItemId: 'new-AdHoc.web-analytics-tab-a' as any,
            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
        }
        const secondProps: InsightLogicProps = {
            dashboardItemId: 'new-AdHoc.web-analytics-tab-b' as any,
            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
        }

        const { rerender } = renderHook(({ insightProps }) => useWebTileExportAdapter(worldMapQuery, insightProps), {
            initialProps: { insightProps: firstProps },
        })
        expect(registeredIds()).toContain(insightVizDataNodeKey(firstProps))

        rerender({ insightProps: secondProps })
        expect(registeredIds()).toContain(insightVizDataNodeKey(secondProps))
    })
})
