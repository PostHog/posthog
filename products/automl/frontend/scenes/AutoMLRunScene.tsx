import { useActions, useValues } from 'kea'

import { LemonInput, LemonSelect, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { automlLogic } from './automlLogic'
import { RunInfoGrid, ScoreCards, extractScores } from './specView'

export const scene: SceneExport = {
    component: AutoMLRunScene,
    logic: automlLogic,
}

export default function AutoMLRunScene(): JSX.Element {
    const { runDetail, runDetailLoading, preview, previewLoading, previewArtifact, previewLimit } =
        useValues(automlLogic)
    const { setPreviewArtifact, setPreviewLimit } = useActions(automlLogic)

    if (runDetailLoading && !runDetail) {
        return <LemonSkeleton className="h-64" />
    }
    if (!runDetail) {
        return <NotFound object="AutoML run" />
    }

    const parquetArtifacts = runDetail.artifacts.filter((a) => a.endsWith('.parquet'))
    const hasScores = Object.keys(extractScores(runDetail.manifest)).length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name={`${runDetail.task_name} · ${runDetail.id}`}
                description={runDetail.is_current ? 'Currently shipped run.' : 'Historical run.'}
                resourceType={{ type: 'task' }}
                actions={
                    <LemonButton to={urls.automlTask(runDetail.task_name)} type="secondary">
                        ← Back to task
                    </LemonButton>
                }
            />

            <Section title="Scores">
                {hasScores ? (
                    <ScoreCards manifest={runDetail.manifest} />
                ) : (
                    <p className="text-muted">No scores in the manifest.</p>
                )}
            </Section>

            <Section title="Run info">
                <RunInfoGrid manifest={runDetail.manifest} />
            </Section>

            <Section title="Parquet preview">
                {parquetArtifacts.length === 0 ? (
                    <p className="text-muted">No parquet artifacts on this run.</p>
                ) : (
                    <>
                        <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <LemonSelect
                                value={previewArtifact}
                                options={parquetArtifacts.map((a) => ({ value: a, label: a }))}
                                onChange={(value) => setPreviewArtifact(value)}
                            />
                            <LemonInput
                                type="number"
                                value={previewLimit}
                                onChange={(value) => setPreviewLimit(Math.max(1, Math.min(200, Number(value) || 50)))}
                                className="w-24"
                            />
                        </div>
                        {previewLoading ? (
                            <LemonSkeleton className="h-48" />
                        ) : preview ? (
                            <>
                                <p className="text-xs text-muted mb-2">
                                    Showing {preview.returned_rows} of {preview.total_rows.toLocaleString()} rows
                                </p>
                                <LemonTable
                                    dataSource={preview.rows.map((row, idx) => ({ __idx: idx, ...row }))}
                                    rowKey="__idx"
                                    columns={preview.columns.map((col) => ({
                                        title: col,
                                        dataIndex: col,
                                        render: (value) => (
                                            <span className="font-mono text-xs">{formatCell(value)}</span>
                                        ),
                                    }))}
                                />
                            </>
                        ) : (
                            <p className="text-muted">No preview available for this artifact.</p>
                        )}
                    </>
                )}
            </Section>

            <Section title="Artifacts">
                <ul className="text-xs font-mono space-y-1">
                    {runDetail.artifacts.map((a) => (
                        <li key={a}>{a}</li>
                    ))}
                </ul>
            </Section>
        </SceneContent>
    )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <h3 className="text-base font-semibold m-0">{title}</h3>
            {children}
        </section>
    )
}

function formatCell(value: unknown): string {
    if (value === null || value === undefined) {
        return '—'
    }
    if (typeof value === 'number') {
        return Number.isInteger(value) ? value.toString() : value.toFixed(4)
    }
    if (typeof value === 'object') {
        return JSON.stringify(value)
    }
    return String(value)
}
