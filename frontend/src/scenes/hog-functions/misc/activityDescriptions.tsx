import { Suspense } from 'react'

import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { isObject } from 'lib/utils/guards'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { HogFunctionTypeType } from '~/types'

import { humanizeHogFunctionType } from '../hog-function-utils'
import type { DiffProps } from './Diff'

const STAGED_CHANGES = 'changed the staged changes'

const nameOrLinkToHogFunction = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name?.trim() ? name : 'Untitled hog function'
    return id ? <Link to={urls.hogFunction(id)}>{displayName}</Link> : displayName
}

const LazyDiff = lazyWithRetry(() => import('./Diff').then((m) => ({ default: m.Diff })))

/** Lazy so the activity describer registry (imported app-wide) doesn't pull monaco into its chunk. */
export function Diff(props: DiffProps): JSX.Element {
    return (
        <Suspense
            fallback={
                <div className="min-h-[300px]">
                    <Spinner />
                </div>
            }
        >
            <LazyDiff {...props} />
        </Suspense>
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

type HogFunctionChange = { inline: string | JSX.Element; inlist: string | JSX.Element }

function describeHogFunctionInputs(change: ActivityChange): HogFunctionChange {
    const beforeValues = isObject(change.before) ? (change.before as Record<string, { value?: unknown }>) : {}
    const afterValues = isObject(change.after) ? (change.after as Record<string, { value?: unknown }>) : {}

    const changedFields = Object.entries(afterValues)
        .map(([key, value]) => {
            const before = JSON.stringify(beforeValues[key]?.value)
            const after = JSON.stringify(value?.value)

            if (before !== after) {
                return (
                    <DiffLink key={key} before={before} after={after}>
                        {key}
                    </DiffLink>
                )
            }
            return null
        })
        .filter((x): x is JSX.Element => !!x)

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

    return {
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
    }
}

function describeHogFunctionCode(change: ActivityChange, field: string): HogFunctionChange {
    const code = (
        <DiffLink
            language={field === 'hog' ? 'hog' : 'json'}
            before={typeof change.before === 'string' ? change.before : JSON.stringify(change.before, null, 2)}
            after={typeof change.after === 'string' ? change.after : JSON.stringify(change.after, null, 2)}
        >
            {field === 'hog' ? 'source code' : field === 'inputs_schema' ? 'inputs schema' : field}
        </DiffLink>
    )

    return { inline: <>updated {code} for</>, inlist: <>updated {code}</> }
}

const HOG_FUNCTION_DIFF_FIELDS = new Set(['inputs_schema', 'filters', 'hog', 'name', 'description', 'masking'])

function describeHogFunctionField(change: ActivityChange, objectNoun: string): HogFunctionChange {
    if (change.field && HOG_FUNCTION_DIFF_FIELDS.has(change.field)) {
        return describeHogFunctionCode(change, change.field)
    }
    switch (change.field) {
        case 'encrypted_inputs':
            return { inline: 'updated encrypted inputs for', inlist: 'updated encrypted inputs' }
        case 'inputs':
            return describeHogFunctionInputs(change)
        case 'deleted': {
            const verb = change.after ? 'deleted' : 'undeleted'
            return { inline: verb, inlist: `${verb} the ${objectNoun}` }
        }
        case 'enabled': {
            const verb = change.after ? 'enabled' : 'disabled'
            return { inline: verb, inlist: `${verb} the ${objectNoun}` }
        }
        case 'priority':
            return {
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
            }
        default:
            return {
                inline: `updated unknown field: ${change.field}`,
                inlist: `updated unknown field: ${change.field}`,
            }
    }
}

function describeHogFunctionUpdate(logItem: ActivityLogItem, objectNoun: string): HumanizedChange {
    const changes: HogFunctionChange[] = []
    for (const change of logItem.detail.changes ?? []) {
        // Both are masked server-side, so there is nothing to diff — say the staged config
        // changed and let the reader open it in the builder. A staged edit usually touches
        // both fields, so collapse them into one entry.
        if (change.field === 'draft' || change.field === 'draft_encrypted_inputs') {
            if (!changes.some((c) => c.inlist === STAGED_CHANGES)) {
                changes.push({ inline: `${STAGED_CHANGES} on`, inlist: STAGED_CHANGES })
            }
            continue
        }
        changes.push(describeHogFunctionField(change, objectNoun))
    }
    const functionName = nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)

    return {
        summary: activityLogSummary(
            logItem,
            <SentenceList
                listParts={changes.length ? changes.map((change) => change.inlist) : [`Updated the ${objectNoun}`]}
            />,
            functionName
        ),
        description:
            changes.length == 1 ? (
                <>
                    <ActivityLogUserName logItem={logItem} /> {changes[0].inline} the {objectNoun}: {functionName}
                </>
            ) : (
                <div>
                    <ActivityLogUserName logItem={logItem} /> updated the {objectNoun}: {functionName}
                    <ul className="ml-5 list-disc">
                        {changes.map((c, i) => (
                            <li key={i}>{c.inlist}</li>
                        ))}
                    </ul>
                </div>
            ),
    }
}

export function hogFunctionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFunction') {
        console.error('HogFunction describer received a non-HogFunction activity')
        return { description: null }
    }

    const rawType = logItem?.detail.type as HogFunctionTypeType | undefined
    const objectNoun = rawType ? humanizeHogFunctionType(rawType) : 'hog function'

    if (logItem.activity == 'created') {
        return {
            summary: activityLogSummary(
                logItem,
                `Created the ${objectNoun}`,
                nameOrLinkToHogFunction(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the {objectNoun}:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            summary: activityLogSummary(
                logItem,
                `Deleted the ${objectNoun}`,
                logItem.detail.name || 'Untitled hog function'
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the {objectNoun}: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'restored') {
        const functionName = nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)

        return {
            summary: activityLogSummary(logItem, `Restored the ${objectNoun}`, functionName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> restored the {objectNoun}: {functionName}
                </>
            ),
        }
    }

    const draftActivities: Record<string, string> = {
        draft_updated: 'staged changes for review on',
        published: 'published the staged changes to',
        draft_discarded: 'discarded the staged changes on',
        revision_restored: 'staged an earlier version for review on',
    }
    if (logItem.activity in draftActivities) {
        return {
            summary: activityLogSummary(
                logItem,
                `${draftActivities[logItem.activity]} the ${objectNoun}`,
                nameOrLinkToHogFunction(logItem.item_id, logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> {draftActivities[logItem.activity]} the {objectNoun}:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return describeHogFunctionUpdate(logItem, objectNoun)
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name))
}
