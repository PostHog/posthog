import React, { useEffect } from 'react'
import { fromParams } from 'lib/utils'
import { CloseButton } from 'lib/components/CloseButton'
import { CohortGroup } from './CohortGroup'
import { cohortLogic } from './cohortLogic'
import { Button, Card, Input } from 'antd'
import { useValues, useActions } from 'kea'
import { People } from './People'

const isSubmitDisabled = (cohorts) => {
    if (cohorts && cohorts.groups) return !cohorts.groups.some((group) => Object.keys(group).length)
    return true
}

export function Cohort({ onChange, cohort }) {
    console.log(cohort)
    const { setCohort, saveCohort } = useActions(cohortLogic({ onChange, id: cohort.id }))
    const { personProperties } = useValues(cohortLogic({ onChange, id: cohort.id }))
    useEffect(() => {
        setCohort(cohort)
    }, [])

    if (!cohort) return null
    return (
        cohort.groups.length > 0 && (
            <div className="mb">
                    <form
                        onSubmit={(e) => {
                            e.preventDefault()
                            saveCohort(cohort)
                        }}
                    >
                        <div className="mb">
                            <Input
                                required
                                autoFocus
                                placeholder="Cohort name..."
                                value={cohort.name}
                                data-attr="cohort-name"
                                onChange={(e) => setCohort({ ...cohort, name: e.target.value })}
                            />
                        </div>
                        {cohort.groups.map((group, index) => (
                            <>
                                <CohortGroup
                                    key={index}
                                    group={group}
                                    properties={personProperties}
                                    index={index}
                                    onRemove={() => {
                                        cohort.groups.splice(index, 1)
                                        setCohort({ ...cohort })
                                    }}
                                    onChange={(group) => {
                                        cohort.groups[index] = group
                                        setCohort({ ...cohort })
                                    }}
                                />
                                {index < cohort.groups.length - 1 && (
                                    <div key={index} className="secondary" style={{ textAlign: 'center', margin: 8 }}>
                                        {' '}
                                        OR{' '}
                                    </div>
                                )}
                            </>
                        ))}
                        <div className="mt">
                            <Button
                                type="primary"
                                htmlType="submit"
                                disabled={isSubmitDisabled(cohort)}
                                data-attr="save-cohort"
                                style={{ marginTop: '1rem' }}
                            >
                                Save cohort
                            </Button>
                            <Button
                                style={{ marginTop: '1rem', marginLeft: 12 }}
                                onClick={() => setCohort({ ...cohort, groups: [...cohort.groups, {}] })}
                            >
                                New group
                            </Button>
                        </div>
                    </form>
                {cohort.id && <People cohortId={cohort.id} />}
            </div>
        )
    )
}
