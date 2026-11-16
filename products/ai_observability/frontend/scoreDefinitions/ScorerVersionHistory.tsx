import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { ScorerSummary } from './ScorerSummary'
import { scorerVersionHistoryLogic } from './scorerVersionHistoryLogic'

export function ScorerVersionHistory({ definition }: { definition: ScoreDefinitionApi }): JSX.Element {
    const logic = scorerVersionHistoryLogic({ definition })
    const { isOpen, history, historyLoading, selectedVersion, versionDraft, cursor } = useValues(logic)
    const { openHistory, closeHistory, selectVersion, loadVersions } = useActions(logic)

    return (
        <>
            <LemonButton
                type="tertiary"
                size="xsmall"
                onClick={openHistory}
                data-attr="aio-scorer-version-history-open"
            >
                Version history
            </LemonButton>
            <LemonModal
                title="Version history"
                isOpen={isOpen}
                onClose={closeHistory}
                width={640}
                data-attr="aio-scorer-version-history"
                footer={
                    <LemonButton type="primary" onClick={closeHistory} data-attr="aio-scorer-version-history-close">
                        Close
                    </LemonButton>
                }
            >
                <div className="flex flex-col gap-4">
                    <p className="text-muted mb-0">Saved versions are read-only.</p>
                    {history.error && (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => loadVersions(cursor ?? undefined),
                                loading: historyLoading,
                                'data-attr': 'aio-scorer-version-history-retry',
                            }}
                        >
                            {history.error}
                        </LemonBanner>
                    )}
                    {historyLoading && !history.results.length ? (
                        <LemonSkeleton className="h-64" />
                    ) : !history.results.length && !history.error ? (
                        <p className="mb-0">No saved versions are available.</p>
                    ) : selectedVersion && versionDraft ? (
                        <>
                            <div className="flex flex-wrap items-center gap-3">
                                <LemonSelect
                                    aria-label="Scorer version"
                                    value={selectedVersion.id}
                                    onChange={selectVersion}
                                    options={history.results.map((version) => ({
                                        value: version.id,
                                        label: `Version ${version.version}${version.version === definition.current_version ? ' (current)' : ''}`,
                                    }))}
                                    data-attr="aio-scorer-version-history-select"
                                />
                                {history.nextCursor && (
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        loading={historyLoading}
                                        onClick={() => loadVersions(history.nextCursor!)}
                                        data-attr="aio-scorer-version-history-older"
                                    >
                                        Load older versions
                                    </LemonButton>
                                )}
                            </div>
                            <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted">
                                <span>
                                    Created <TZLabel time={selectedVersion.created_at} />
                                </span>
                                <CopyToClipboardInline
                                    explicitValue={selectedVersion.id}
                                    description="Scorer version ID"
                                >
                                    Copy version ID
                                </CopyToClipboardInline>
                            </div>
                            <ScorerSummary
                                draft={versionDraft}
                                heading={`Version ${selectedVersion.version}`}
                                inputSummary={
                                    selectedVersion.composition ? (
                                        <ul className="list-none m-0 p-0 flex flex-col gap-3">
                                            {selectedVersion.composition.inputs.map((input) => (
                                                <li key={input.alias} className="flex flex-col gap-1 text-sm">
                                                    <span className="font-mono">{input.alias}</span>
                                                    <CopyToClipboardInline
                                                        explicitValue={input.scorer_version_id}
                                                        description="Input scorer version ID"
                                                    >
                                                        <span className="font-mono text-xs break-all">
                                                            {input.scorer_version_id}
                                                        </span>
                                                    </CopyToClipboardInline>
                                                </li>
                                            ))}
                                        </ul>
                                    ) : undefined
                                }
                            />
                        </>
                    ) : null}
                </div>
            </LemonModal>
        </>
    )
}
