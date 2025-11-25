import { ItemCategory, ItemRenderer, TimelineItem } from '..'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { ErrorTrackingException, ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { BasePreview, EventLoader } from './base'

export interface ExceptionItem extends TimelineItem {
    payload: {
        runtime: ErrorTrackingRuntime
        type: string
        message: string
        issue_id: string
        fingerprint: string
    }
}

export const exceptionRenderer: ItemRenderer<ExceptionItem> = {
    sourceIcon: ({ item }) => <RuntimeIcon runtime={item.payload.runtime} />,
    categoryIcon: <IconWarning />,
    render: ({ item }): JSX.Element => {
        const name = item.payload.type
        const description = item.payload.message
        const eventIssueId = item.payload.issue_id
        return (
            <BasePreview
                name={name}
                description={
                    <Link
                        className="text-secondary hover:text-accent"
                        subtle
                        to={urls.errorTrackingIssue(eventIssueId, {
                            fingerprint: item.payload.fingerprint,
                            timestamp: item.timestamp.toISOString(),
                        })}
                    >
                        {description}
                    </Link>
                }
                descriptionTitle={description}
            />
        )
    },
}

export class ExceptionItemLoader extends EventLoader<ExceptionItem> {
    select(): string[] {
        return ['uuid', 'timestamp', 'properties']
    }

    where(): string[] {
        return ["equals(event, '$exception')"]
    }

    buildItem(evt: any): ExceptionItem {
        const properties = JSON.parse(evt[2])
        return {
            id: evt[0],
            category: ItemCategory.ERROR_TRACKING,
            timestamp: dayjs.utc(evt[1]),
            payload: {
                runtime: getRuntimeFromLib(properties['$lib']),
                type: getExceptionType(properties['$exception_list']),
                message: getExceptionMessage(properties['$exception_list']),
                fingerprint: properties['$exception_fingerprint'],
                issue_id: properties['$exception_issue_id'],
            },
        } as ExceptionItem
    }
}

function getExceptionType(exceptionList: ErrorTrackingException[]): string | undefined {
    try {
        const firstException = exceptionList[0]
        if (firstException) {
            return firstException.type
        }
    } catch {
        return undefined
    }
}

function getExceptionMessage(exceptionList: ErrorTrackingException[]): string | undefined {
    try {
        const firstException = exceptionList[0]
        if (firstException) {
            return firstException.value
        }
    } catch {
        return undefined
    }
}
