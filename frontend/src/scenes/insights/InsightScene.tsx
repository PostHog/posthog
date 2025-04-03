import { CORE_FILTER_DEFINITIONS_BY_GROUP as NEW_TAXONOMY } from '@posthog/taxonomy'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { useEffect, useMemo } from 'react'
import { Insight } from 'scenes/insights/Insight'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CORE_FILTER_DEFINITIONS_BY_GROUP as LEGACY_TAXONOMY } from '~/lib/taxonomy'
import { NodeKind } from '~/queries/schema/schema-general'
import { CoreFilterDefinition, ItemMode } from '~/types'

type TaxonomyGroup = Record<string, CoreFilterDefinition>
type TaxonomyType = Record<string, TaxonomyGroup>

export function InsightSceneTmp(): JSX.Element {
    const compareTaxonomies = useMemo(() => {
        const allKeys = new Set([...Object.keys(NEW_TAXONOMY), ...Object.keys(LEGACY_TAXONOMY)])

        const comparison = {
            onlyInNew: [] as string[],
            onlyInLegacy: [] as string[],
            inBoth: [] as string[],
            differences: [] as {
                key: string
                type: string
                newProps: CoreFilterDefinition | undefined
                legacyProps: CoreFilterDefinition | undefined
            }[],
        }

        allKeys.forEach((key) => {
            if (key in NEW_TAXONOMY && !(key in LEGACY_TAXONOMY)) {
                comparison.onlyInNew.push(key)
            } else if (!(key in NEW_TAXONOMY) && key in LEGACY_TAXONOMY) {
                comparison.onlyInLegacy.push(key)
            } else if (key in NEW_TAXONOMY && key in LEGACY_TAXONOMY) {
                comparison.inBoth.push(key)

                // Compare properties within each key
                const newProps = (NEW_TAXONOMY as TaxonomyType)[key]
                const legacyProps = (LEGACY_TAXONOMY as TaxonomyType)[key]
                const allPropKeys = new Set([...Object.keys(newProps), ...Object.keys(legacyProps)])

                allPropKeys.forEach((propKey) => {
                    const newProp = newProps[propKey]
                    const legacyProp = legacyProps[propKey]

                    if (!newProp || !legacyProp || JSON.stringify(newProp) !== JSON.stringify(legacyProp)) {
                        comparison.differences.push({
                            key: `${key}.${propKey}`,
                            type: key,
                            newProps: newProp,
                            legacyProps: legacyProp,
                        })
                    }
                })
            }
        })

        return comparison
    }, [])

    return (
        <div className="p-4">
            <h2 className="text-2xl mb-4">Taxonomy Comparison</h2>

            <div className="space-y-6">
                <section>
                    <h3 className="text-xl mb-2">Categories Present</h3>
                    <div className="grid grid-cols-3 gap-4">
                        <div>
                            <h4 className="font-bold mb-2">Only in taxonomy.py</h4>
                            <ul className="list-disc pl-4">
                                {compareTaxonomies.onlyInNew.map((key) => (
                                    <li key={key}>{key}</li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h4 className="font-bold mb-2">Only in taxonomy.tsx</h4>
                            <ul className="list-disc pl-4">
                                {compareTaxonomies.onlyInLegacy.map((key) => (
                                    <li key={key}>{key}</li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h4 className="font-bold mb-2">Present in Both</h4>
                            <ul className="list-disc pl-4">
                                {compareTaxonomies.inBoth.map((key) => (
                                    <li key={key}>{key}</li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </section>

                <section>
                    <h3 className="text-xl mb-2">Property Differences ({compareTaxonomies.differences.length})</h3>
                    <div className="space-y-4">
                        {compareTaxonomies.differences.map((diff) => (
                            <div key={diff.key} className="border p-4 rounded">
                                <h4 className="font-bold">{diff.key}</h4>
                                <div className="grid grid-cols-2 gap-4 mt-2">
                                    <div>
                                        <h5 className="font-semibold">taxonomy.py</h5>
                                        <pre className="bg-black p-2 rounded mt-1 text-sm">
                                            {JSON.stringify(diff.newProps, null, 2)}
                                        </pre>
                                    </div>
                                    <div>
                                        <h5 className="font-semibold">taxonomy.tsx</h5>
                                        <pre className="bg-black p-2 rounded mt-1 text-sm">
                                            {JSON.stringify(diff.legacyProps, null, 2)}
                                        </pre>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            </div>
        </div>
    )
}

export function InsightScene(): JSX.Element {
    const { insightId, insight, insightLogicRef, insightMode } = useValues(insightSceneLogic)

    useEffect(() => {
        // Redirect data viz nodes to the sql editor
        if (insightId && insight?.query?.kind === NodeKind.DataVisualizationNode && insightMode === ItemMode.Edit) {
            router.actions.push(urls.sqlEditor(undefined, undefined, insightId))
        }
    }, [insightId, insight?.query?.kind, insightMode])

    if (
        insightId === 'new' ||
        (insightId &&
            insight?.id &&
            insight?.short_id &&
            (insight?.query?.kind !== NodeKind.DataVisualizationNode || insightMode !== ItemMode.Edit))
    ) {
        return <Insight insightId={insightId} />
    }

    if (insightLogicRef?.logic?.values?.insightLoading) {
        return <InsightSkeleton />
    }

    return <NotFound object="insight" />
}

export const scene: SceneExport = {
    component: InsightSceneTmp,
    logic: insightSceneLogic,
}
