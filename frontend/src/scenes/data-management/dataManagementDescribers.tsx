import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    ChangeMapping,
    Description,
    detectBoolean,
    HumanizedChange,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { pluralize } from 'lib/utils'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { IconVerifiedEvent } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const dataManagementActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    description: (change) => {
        return {
            description: [
                <>
                    changed description to <strong>"{change?.after}"</strong>
                </>,
            ],
        }
    },
    tags: function onTags(change) {
        const tagsBefore = change?.before as string[] | null
        const tagsAfter = change?.after as string[] | null
        const addedTags = tagsAfter?.filter((t) => tagsBefore?.indexOf(t) === -1) || []
        const removedTags = tagsBefore?.filter((t) => tagsAfter?.indexOf(t) === -1) || []

        const changes: Description[] = []
        if (addedTags.length) {
            changes.push(
                <>
                    added {pluralize(addedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed {pluralize(removedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }

        return { description: changes }
    },
    verified: (change, logItem) => {
        const verified = detectBoolean(change?.after)
        return {
            description: [
                <>
                    marked {nameAndLink(logItem)} as <strong>{verified ? 'verified' : 'unverified'}</strong>{' '}
                    {verified && <IconVerifiedEvent />}
                </>,
            ],
            suffix: <></>,
        }
    },
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.item_id ? (
        <Link to={urls.eventDefinition(logItem.item_id)}>{logItem?.detail.name || 'unknown'}</Link>
    ) : logItem?.detail.name ? (
        <>{logItem?.detail.name}</>
    ) : (
        <>unknown</>
    )
}

export function dataManagementActivityDescriber(logItem: ActivityLogItem): HumanizedChange {
    if (logItem.scope !== ActivityScope.EVENT_DEFINITION) {
        console.error('data management describer received a non-data-management activity')
        return { description: null }
    }

    if (logItem.activity == 'changed') {
        let changes: Description[] = []
        let changeSuffix: Description = <>on {nameAndLink(logItem)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !dataManagementActionsMapping[change.field]) {
                continue //  updates have to have a "field" to be described
            }

            const actionHandler = dataManagementActionsMapping[change.field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue // // unexpected log from backend is indescribable
            }

            const { description, suffix } = processedChange
            if (description) {
                changes = changes.concat(description)
            }

            if (suffix) {
                changeSuffix = suffix
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong>{logItem.user.first_name}</strong>}
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>deleted</strong> {nameAndLink(logItem)}
                </>
            ),
        }
    }

    // if (logItem.activity == 'installed') {
    //     return {
    //         description: (
    //             <>
    //                 <strong>{logItem.user.first_name}</strong> installed the app: <b>{logItem.detail.name}</b>
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'uninstalled') {
    //     return {
    //         description: (
    //             <>
    //                 <strong>{logItem.user.first_name}</strong> uninstalled the app: <b>{logItem.detail.name}</b>
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'enabled') {
    //     const changes: (string | JSX.Element)[] = []
    //     for (const change of logItem.detail.changes || []) {
    //         const newValue = change.after === SECRET_FIELD_VALUE ? '<secret_value>' : change.after
    //         changes.push(
    //             <>
    //                 field <code>{change.field}</code> set to <code>{newValue}</code>
    //             </>
    //         )
    //     }
    //     return {
    //         description: (
    //             <SentenceList
    //                 listParts={changes}
    //                 prefix={
    //                     <>
    //                         <strong>{logItem.user.first_name}</strong> enabled the app: <b>{logItem.detail.name}</b>{' '}
    //                         with config ID {logItem.item_id}
    //                         {changes.length > 0 ? ', with' : '.'}
    //                     </>
    //                 }
    //             />
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'disabled') {
    //     return {
    //         description: (
    //             <>
    //                 <strong>{logItem.user.first_name}</strong> disabled the app: <b>{logItem.detail.name}</b> with
    //                 config ID {logItem.item_id}.
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'job_triggered' && logItem.detail.trigger?.job_type == 'Export historical events V2') {
    //     const [startDate, endDate] = logItem.detail.trigger.payload.dateRange
    //     return {
    //         description: (
    //             <>
    //                 <strong>{logItem.user.first_name}</strong> started exporting historical events between {startDate}{' '}
    //                 and {endDate} (inclusive).
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'job_triggered' && logItem.detail.trigger) {
    //     return {
    //         description: (
    //             <>
    //                 <strong>{logItem.user.first_name}</strong> triggered job:{' '}
    //                 <code>{logItem.detail.trigger.job_type}</code> with config ID {logItem.item_id}.
    //             </>
    //         ),
    //         extendedDescription: (
    //             <>
    //                 Payload: <code>{JSON.stringify(logItem.detail.trigger.payload, null, 2)}</code>
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'export_success' && logItem.detail.trigger) {
    //     const { dateFrom, dateTo } = logItem.detail.trigger.payload
    //     const startDate = dayjs(dateFrom).format('YYYY-MM-DD')
    //     // :TRICKY: Internally export date range is non-inclusive so transform it to be inclusive
    //     const endDate = dayjs(dateTo).subtract(1, 'day').format('YYYY-MM-DD')
    //
    //     return {
    //         description: (
    //             <>
    //                 Finished exporting historical events between {startDate} and {endDate} (inclusive).
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'export_fail' && logItem.detail.trigger) {
    //     const { dateFrom, dateTo } = logItem.detail.trigger.payload
    //     const startDate = dayjs(dateFrom).format('YYYY-MM-DD')
    //     // :TRICKY: Internally export date range is non-inclusive so transform it to be inclusive
    //     const endDate = dayjs(dateTo).subtract(1, 'day').format('YYYY-MM-DD')
    //
    //     return {
    //         description: (
    //             <>
    //                 Fatal error exporting historical events between {startDate} and {endDate} (inclusive). Check logs
    //                 for more details.
    //             </>
    //         ),
    //     }
    // }
    //
    // if (logItem.activity == 'config_updated') {
    //     const changes: (string | JSX.Element)[] = []
    //     for (const change of logItem.detail.changes || []) {
    //         let changeWording: string | JSX.Element = ''
    //         const changeBefore = change.before === SECRET_FIELD_VALUE ? '<secret_value>' : change.before
    //         const changeAfter = change.after === SECRET_FIELD_VALUE ? '<secret_value>' : change.after
    //         if (change.action === 'created') {
    //             changeWording = (
    //                 <>
    //                     added new field <code>{change.field}</code>" with value <code>{changeAfter}</code>
    //                 </>
    //             )
    //         } else if (change.action === 'deleted') {
    //             changeWording = (
    //                 <>
    //                     removed field <code>{change.field}</code>, which had value <code>{changeBefore}</code>
    //                 </>
    //             )
    //         } else if (change.action === 'changed') {
    //             changeWording = (
    //                 <>
    //                     updated field <code>{change.field}</code> from value <code>{changeBefore}</code> to value{' '}
    //                     <code>{changeAfter}</code>{' '}
    //                 </>
    //             )
    //         }
    //         changes.push(changeWording)
    //     }
    //     return {
    //         description: (
    //             <SentenceList
    //                 prefix={<strong>{logItem.user.first_name}</strong>}
    //                 listParts={changes}
    //                 suffix={
    //                     <>
    //                         on app <b>{logItem.detail.name}</b> with config ID {logItem.item_id}.
    //                     </>
    //                 }
    //             />
    //         ),
    //     }
    // }
    //
    // if (logItem.activity.startsWith('attachment_')) {
    //     for (const change of logItem.detail.changes || []) {
    //         let changeWording: string | JSX.Element = ''
    //
    //         if (logItem.activity === 'attachment_created') {
    //             changeWording = (
    //                 <>
    //                     attached a file <code>{change.after}</code>
    //                 </>
    //             )
    //         } else if (logItem.activity == 'attachment_updated') {
    //             if (change.after === change.before) {
    //                 changeWording = (
    //                     <>
    //                         updated attached file <code>{change.after}</code>
    //                     </>
    //                 )
    //             } else {
    //                 changeWording = (
    //                     <>
    //                         updated attached file from <code>{change.before}</code> to <code>{change.after}</code>
    //                     </>
    //                 )
    //             }
    //         } else if (logItem.activity === 'attachment_deleted') {
    //             changeWording = (
    //                 <>
    //                     deleted attached file <code>{change.before}</code>
    //                 </>
    //             )
    //         }
    //
    //         return {
    //             description: (
    //                 <>
    //                     <strong>{logItem.user.first_name}</strong> {changeWording} on app: <b>{logItem.detail.name}</b>{' '}
    //                     with config ID {logItem.item_id}
    //                 </>
    //             ),
    //         }
    //     }
    // }

    return { description: null }
}
