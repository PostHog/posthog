import { DiffEditor } from '@monaco-editor/react'

import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link } from 'lib/lemon-ui/Link'
import { initHogLanguage } from 'lib/monaco/languages/hog'
import { urls } from 'scenes/urls'

const nameOrLinkToHogFunction = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.hogFunction(id)}>{displayName}</Link> : displayName
}

export interface DiffProps {
    before: string
    after: string
    language?: string
}

export function Diff({ before, after, language }: DiffProps): JSX.Element {
    return (
        <DiffEditor
            height="300px"
            original={before}
            modified={after}
            language={language ?? 'json'}
            onMount={(_, monaco) => {
                if (language === 'hog') {
                    initHogLanguage(monaco)
                }
            }}
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
    )
}

export interface DiffLinkProps extends DiffProps {
    children: string | JSX.Element
}

export function DiffLink({ before, after, language, children }: DiffLinkProps): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="w-[50vw] min-w-[300px]">
                    <Diff before={before} after={after} language={language} />
                </div>
            }
        >
            <span className="Link">{children}</span>
        </LemonDropdown>
    )
}

export function hogFunctionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFunction') {
        console.error('HogFunction describer received a non-HogFunction activity')
        return { description: null }
    }

    const objectNoun = logItem?.detail.type ?? 'hog function'

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the {objectNoun}:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the {objectNoun}: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes: { inline: string | JSX.Element; inlist: string | JSX.Element }[] = []
        for (const change of logItem.detail.changes ?? []) {
            switch (change.field) {
                case 'encrypted_inputs': {
                    changes.push({
                        inline: 'updated encrypted inputs for',
                        inlist: 'updated encrypted inputs',
                    })
                    break
                }
                case 'inputs': {
                    const changedFields: JSX.Element[] = []
                    Object.entries(change.after ?? {}).forEach(([key, value]) => {
                        const before = JSON.stringify(change.before?.[key]?.value)
                        const after = JSON.stringify(value?.value)
                        if (before !== after) {
                            changedFields.push(
                                <DiffLink before={before} after={after}>
                                    {key}
                                </DiffLink>
                            )
                        }
                    })
                    const changedSpans: JSX.Element[] = []
                    for (let index = 0; index < changedFields.length; index++) {
                        if (index !== 0 && index === changedFields.length - 1) {
                            changedSpans.push(<>{' and '}</>)
                        } else if (index > 0) {
                            changedSpans.push(<>{', '}</>)
                        }
                        changedSpans.push(changedFields[index])
                    }
                    const inputOrInputs = changedFields.length === 1 ? 'input' : 'inputs'
                    changes.push({
                        inline: (
                            <>
                                updated the {inputOrInputs} {changedSpans} for
                            </>
                        ),
                        inlist: (
                            <>
                                updated {inputOrInputs}: {changedSpans}
                            </>
                        ),
                    })
                    break
                }
                case 'inputs_schema':
                case 'filters':
                case 'hog':
                case 'name':
                case 'description':
                case 'masking': {
                    const code = (
                        <DiffLink
                            language={change.field === 'hog' ? 'hog' : 'json'}
                            before={
                                typeof change.before === 'string'
                                    ? change.before
                                    : JSON.stringify(change.before, null, 2)
                            }
                            after={
                                typeof change.after === 'string' ? change.after : JSON.stringify(change.after, null, 2)
                            }
                        >
                            {change.field === 'hog'
                                ? 'source code'
                                : change.field === 'inputs_schema'
                                  ? 'inputs schema'
                                  : change.field}
                        </DiffLink>
                    )
                    changes.push({ inline: <>updated {code} for</>, inlist: <>updated {code}</> })
                    break
                }
                case 'deleted': {
                    if (change.after) {
                        changes.push({ inline: 'deleted', inlist: `deleted the ${objectNoun}` })
                    } else {
                        changes.push({ inline: 'undeleted', inlist: `undeleted the ${objectNoun}` })
                    }
                    break
                }
                case 'enabled': {
                    if (change.after) {
                        changes.push({ inline: 'enabled', inlist: `enabled the ${objectNoun}` })
                    } else {
                        changes.push({ inline: 'disabled', inlist: `disabled the ${objectNoun}` })
                    }
                    break
                }
                case 'priority': {
                    changes.push({
                        inline: (
                            <>
                                changed priority from {change.before} to {change.after} for{' '}
                            </>
                        ),
                        inlist: (
                            <>
                                changed priority from {change.before} to {change.after} for{' '}
                            </>
                        ),
                    })
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
                        <strong>{name}</strong> {changes[0].inline} the {objectNoun}: {functionName}
                    </>
                ) : (
                    <div>
                        <strong>{name}</strong> updated the {objectNoun}: {functionName}
                        <ul className="ml-5 list-disc">
                            {changes.map((c, i) => (
                                <li key={i}>{c.inlist}</li>
                            ))}
                        </ul>
                    </div>
                ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToHogFunction(logItem?.detail.short_id))
}
