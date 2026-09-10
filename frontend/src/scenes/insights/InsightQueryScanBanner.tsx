import { useValues } from 'kea'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryScanBanner } from '~/queries/nodes/DataNode/QueryScanBanner'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { InsightLogicProps } from '~/types'

export function InsightQueryScanBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { queryScan } = useValues(dataNodeLogic({ key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps))

    return <QueryScanBanner queryScan={queryScan} />
}
