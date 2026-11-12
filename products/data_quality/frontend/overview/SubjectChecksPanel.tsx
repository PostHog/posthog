import { useValues } from 'kea'

import { DataQualitySchedule } from '../DataQualitySchedule'
import { SubjectTypeEnumApi } from '../generated/api.schemas'
import { SubjectGroup, dataQualityOverviewLogic } from './dataQualityOverviewLogic'
import { SubjectChecks } from './SubjectChecks'

const SCHEDULED_SUBJECT_TYPES: string[] = [SubjectTypeEnumApi.Metric, SubjectTypeEnumApi.PosthogTable]

export function SubjectChecksPanel({ group }: { group: SubjectGroup }): JSX.Element {
    const { scheduleBySubjectKey, subjectSchedulesLoading } = useValues(dataQualityOverviewLogic)

    return (
        <>
            {SCHEDULED_SUBJECT_TYPES.includes(group.subjectType) && group.subjectUuid ? (
                <div className="px-2 pt-2">
                    <DataQualitySchedule
                        subjectType={group.subjectType}
                        subjectId={group.subjectUuid}
                        initialSchedule={
                            scheduleBySubjectKey[group.subjectKey] ?? (subjectSchedulesLoading ? null : undefined)
                        }
                        poll={false}
                    />
                </div>
            ) : null}
            <SubjectChecks group={group} />
        </>
    )
}
