import { useValues } from 'kea'

import { SubjectTypeEnumApi } from '../generated/api.schemas'
import { QuillDataQualitySchedule } from '../QuillDataQualitySchedule'
import { SubjectGroup, dataQualityOverviewLogic } from './dataQualityOverviewLogic'
import { QuillSubjectChecks } from './QuillSubjectChecks'

const SCHEDULED_SUBJECT_TYPES: string[] = [SubjectTypeEnumApi.Metric, SubjectTypeEnumApi.PosthogTable]

export function QuillSubjectChecksPanel({ group }: { group: SubjectGroup }): JSX.Element {
    const { scheduleBySubjectKey, subjectSchedulesLoading } = useValues(dataQualityOverviewLogic)

    return (
        <div className="flex flex-col gap-2">
            {SCHEDULED_SUBJECT_TYPES.includes(group.subjectType) && group.subjectUuid ? (
                <QuillDataQualitySchedule
                    subjectType={group.subjectType}
                    subjectId={group.subjectUuid}
                    initialSchedule={
                        scheduleBySubjectKey[group.subjectKey] ?? (subjectSchedulesLoading ? null : undefined)
                    }
                    poll={false}
                />
            ) : null}
            <QuillSubjectChecks group={group} />
        </div>
    )
}
