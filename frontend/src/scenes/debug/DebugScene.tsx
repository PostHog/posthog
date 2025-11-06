import { useActions, useValues } from 'kea'

import { IconDatabaseBolt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DebugSceneQuery } from 'scenes/debug/DebugSceneQuery'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { stringifiedExamples } from '~/queries/examples'

import { debugSceneLogic } from './debugSceneLogic'

export function DebugScene(): JSX.Element {
    const { query1, query2 } = useValues(debugSceneLogic)
    const { setQuery1, setQuery2 } = useActions(debugSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <SceneContent className="QueryScene">
            <SceneTitleSection
                name="Debug"
                resourceType={{ type: 'debug', forceIcon: <IconDatabaseBolt /> }}
                actions={
                    <>
                        <LemonButton
                            size="small"
                            active={!!query2}
                            onClick={() => (query2 ? setQuery2('') : setQuery2(query1))}
                        >
                            Split
                        </LemonButton>
                        <LemonButton
                            size="small"
                            active={query1 === stringifiedExamples.HogQLRaw}
                            onClick={() => setQuery1(stringifiedExamples.HogQLRaw)}
                        >
                            SQL Debug
                        </LemonButton>
                        {featureFlags[FEATURE_FLAGS.HOG] ? (
                            <LemonButton
                                size="small"
                                active={query1 === stringifiedExamples.Hoggonacci}
                                onClick={() => setQuery1(stringifiedExamples.Hoggonacci)}
                            >
                                Hog
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            size="small"
                            active={query1 === stringifiedExamples.HogQLTable}
                            onClick={() => setQuery1(stringifiedExamples.HogQLTable)}
                        >
                            SQL Table
                        </LemonButton>
                        <LemonButton
                            size="small"
                            active={query1 === stringifiedExamples.Events}
                            onClick={() => setQuery1(stringifiedExamples.Events)}
                        >
                            Any Query
                        </LemonButton>
                        <LemonLabel>
                            <LemonSelect
                                size="small"
                                placeholder="More sample queries"
                                options={Object.entries(stringifiedExamples)
                                    .filter(([k]) => k !== 'HogQLTable' && k !== 'HogQLRaw')
                                    .map(([k, v]) => {
                                        return { label: k, value: v }
                                    })}
                                onChange={(v) => {
                                    if (v) {
                                        setQuery1(v)
                                    }
                                }}
                            />
                        </LemonLabel>
                    </>
                }
            />

            <div className="flex gap-2">
                <div className="flex-1 w-1/2">
                    <DebugSceneQuery query={query1} setQuery={setQuery1} queryKey="new-hogql-debug-1" />
                </div>
                {query2 ? (
                    <div className="flex-1 w-1/2">
                        <DebugSceneQuery query={query2} setQuery={setQuery2} queryKey="new-hogql-debug-2" />
                    </div>
                ) : null}
            </div>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: DebugScene,
    logic: debugSceneLogic,
}
