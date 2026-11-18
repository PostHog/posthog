import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

// The backend stores ids only, because every activity-log reader sees these rows.
interface AccessControlActivityContext {
    resource: string
    resource_id: string | null
    access_level: string
    role_id: string | null
    organization_member_id: string | null
}

function subjectFor(context: AccessControlActivityContext): string {
    if (context.role_id) {
        return 'a role'
    }
    if (context.organization_member_id) {
        return 'a member'
    }
    return 'everyone'
}

function targetFor(context: AccessControlActivityContext): JSX.Element {
    const resource = context.resource.replace(/_/g, ' ')
    if (context.resource === 'project') {
        return <strong>this project</strong>
    }
    if (!context.resource_id) {
        return <strong>every {resource}</strong>
    }
    return (
        <strong>
            {resource} {context.resource_id}
        </strong>
    )
}

export function accessControlActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const context = logItem.detail.context as AccessControlActivityContext | null | undefined
    if (!context?.resource) {
        return defaultDescriber(logItem, asNotification)
    }

    const subject = subjectFor(context)
    const target = targetFor(context)
    const levelChange = logItem.detail.changes?.find((change) => change.field === 'access_level')

    let action: string
    if (logItem.activity === 'created') {
        action = `set access for ${subject} to ${context.access_level} on`
    } else if (logItem.activity === 'deleted') {
        action = `removed the access rule for ${subject} on`
    } else if (levelChange) {
        action = `changed access for ${subject} from ${levelChange.before} to ${levelChange.after} on`
    } else {
        return defaultDescriber(logItem, asNotification, target)
    }

    return {
        summary: activityLogSummary(logItem, action, target),
        description: (
            <>
                <ActivityLogUserName logItem={logItem} /> {action} {target}
            </>
        ),
    }
}
