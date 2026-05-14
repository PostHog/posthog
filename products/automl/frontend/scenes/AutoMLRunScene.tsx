import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSelect, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

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

const PAGE_SIZE_OPTIONS: { value: number; label: string }[] = [
    { value: 10, label: '10' },
    { value: 25, label: '25' },
    { value: 100, label: '100' },
]

export default function AutoMLRunScene(): JSX.Element {
    const { runDetail, runDetailLoading, preview, previewLoading, previewArtifact, previewPageSize, previewPage } =
        useValues(automlLogic)
    const { setPreviewArtifact, setPreviewPageSize, setPreviewPage } = useActions(automlLogic)

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
                            <LemonSegmentedButton
                                size="small"
                                value={previewPageSize}
                                onChange={(value) => setPreviewPageSize(value)}
                                options={PAGE_SIZE_OPTIONS}
                            />
                        </div>
                        {previewLoading && !preview ? (
                            <LemonSkeleton className="h-48" />
                        ) : preview ? (
                            <LemonTable
                                loading={previewLoading}
                                dataSource={preview.rows.map((row, idx) => ({ __idx: idx, ...row }))}
                                rowKey="__idx"
                                columns={preview.columns.map((col) => ({
                                    title: col,
                                    dataIndex: col,
                                    render: (value) => <span className="font-mono text-xs">{formatCell(value)}</span>,
                                }))}
                                pagination={{
                                    controlled: true,
                                    pageSize: previewPageSize,
                                    currentPage: previewPage,
                                    entryCount: preview.total_rows,
                                    onBackward: () => setPreviewPage(previewPage - 1),
                                    onForward: () => setPreviewPage(previewPage + 1),
                                }}
                            />
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
