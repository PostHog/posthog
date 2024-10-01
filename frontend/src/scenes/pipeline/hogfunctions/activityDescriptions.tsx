import { DiffEditor } from '@monaco-editor/react'
import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

const nameOrLinkToHogFunction = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? (
        <Link to={urls.pipelineNode(PipelineStage.Destination, `hog-${id}`, PipelineNodeTab.Configuration)}>
            {displayName}
        </Link>
    ) : (
        displayName
    )
}

export interface DiffProps {
    before: string
    after: string
    language?: string
}
export function Diff({ before, after, language }: DiffProps): JSX.Element {
    return (
        <div className="w-[50vw] min-w-[300px]">
            <DiffEditor
                height="300px"
                original={before}
                modified={after}
                language={language ?? 'json'}
                options={{
                    lineNumbers: 'off',
                    minimap: { enabled: false },
                    folding: false,
                    wordWrap: 'on',
                    renderLineHighlight: 'none',
                    scrollbar: { vertical: 'auto', horizontal: 'hidden' },
                    overviewRulerBorder: false,
                    hideCursorInOverviewRuler: true,
                    overviewRulerLanes: 0,
                    tabFocusMode: true,
                    enableSplitViewResizing: false,
                    renderSideBySide: false,
                    readOnly: true,
                }}
            />
        </div>
    )
}

export function hogFunctionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFunction') {
        console.error('HogFunction describer received a non-HogFunction activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the hog function:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the hog function: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes: { inline: string | JSX.Element; inlist: string | JSX.Element }[] = []
        for (const change of logItem.detail.changes ?? []) {
            switch (change.field) {
                case 'encrypted_inputs': {
                    changes.push({ inline: 'updated secrets for', inlist: 'updated secrets' })
                    break
                }
                case 'inputs': {
                    const changedFields: JSX.Element[] = []
                    Object.entries(change.after ?? {}).forEach(([key, value]) => {
                        const before = JSON.stringify(change.before?.[key]?.value)
                        const after = JSON.stringify(value?.value)
                        if (before !== after) {
                            if (changedFields.length > 0) {
                                changedFields.push(<span>, </span>)
                            }
                            changedFields.push(
                                <LemonDropdown
                                    overlay={
                                        <div>
                                            <div>{`inputs.${key}:`}</div>
                                            <Diff before={before} after={after} />
                                        </div>
                                    }
                                >
                                    <span className="Link">{key}</span>
                                </LemonDropdown>
                            )
                        }
                    })
                    changes.push({
                        inline: <>updated fields: {changedFields}</>,
                        inlist: <>updated fields: {changedFields}</>,
                    })
                    break
                }
                case 'filters': {
                    changes.push({ inline: 'updated filters of', inlist: 'updated filters' })
                    break
                }
                case 'deleted': {
                    if (change.after) {
                        changes.push({ inline: 'deleted', inlist: 'deleted' })
                    } else {
                        changes.push({ inline: 'undeleted', inlist: 'undeleted' })
                    }
                    break
                }
                case 'hog': {
                    const code = (
                        <LemonDropdown
                            overlay={
                                <Diff
                                    language="hog"
                                    before={String(change.before ?? '')}
                                    after={String(change.after ?? '')}
                                />
                            }
                        >
                            <span className="Link">updated hog code</span>
                        </LemonDropdown>
                    )
                    changes.push({ inline: <>{code} for</>, inlist: code })
                    break
                }
                case 'name': {
                    changes.push({ inline: `name: ${change.after}`, inlist: `name: ${change.after}` })
                    break
                }
                case 'description': {
                    changes.push({ inline: `description: ${change.after}`, inlist: `description: ${change.after}` })
                    break
                }
                case 'enabled': {
                    if (change.after) {
                        changes.push({ inline: 'enabled', inlist: 'enabled' })
                    } else {
                        changes.push({ inline: 'disabled', inlist: 'disabled' })
                    }
                    break
                }
                case 'masking': {
                    const value = (change.after as any)?.hash
                    if (value === 'all') {
                        changes.push({ inline: 'set to run every time for', inlist: 'set to run every time' })
                    } else {
                        changes.push({ inline: 'updated throttling for', inlist: 'updated throttling' })
                    }
                    break
                }
                default:
                    changes.push({
                        inline: `updated unknown field: ${change.field}`,
                        inlist: `updated unknown field: ${change.field}`,
                    })
            }
        }
        const name = userNameForLogItem(logItem)
        const functionName = nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)

        return {
            description:
                changes.length == 1 ? (
                    <>
                        <strong>{name}</strong> {changes[0].inline} the hog function: {functionName}
                    </>
                ) : (
                    <div>
                        <strong>{name}</strong> updated the hog function: {functionName}
                        <ul>
                            {changes.map((c, i) => (
                                <li key={i}>- {c.inlist}</li>
                            ))}
                        </ul>
                    </div>
                ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToHogFunction(logItem?.detail.short_id))
}
