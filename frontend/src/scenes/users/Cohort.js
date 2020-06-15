import React from 'react'
import { Card, CloseButton, fromParams } from 'lib/utils'
import { CohortGroup } from './CohortGroup'
import { cohortLogic } from './cohortLogic'
import { Button } from 'antd'

import { useValues, useActions } from 'kea'
import { router } from 'kea-router'
import _ from 'lodash'

const isSubmitDisabled = cohorts => {
    if (cohorts && cohorts.groups) return !cohorts.groups.some(group => !_.isEmpty(group))
    return true
}

export function Cohort({ onChange }) {
    const { setCohort, saveCohort } = useActions(cohortLogic({ onChange, id: fromParams()['cohort'] }))
    const { personProperties, cohort } = useValues(cohortLogic({ onChange, id: fromParams()['cohort'] }))

    if (!cohort) return null
    return cohort.groups.length === 0 ? (
        <Button
            style={{ marginBottom: '1rem', marginRight: 12 }}
            onClick={() => setCohort({ groups: [{}] })}
            type="primary"
            data-attr="create-cohort"
        >
            + New Cohort
        </Button>
    ) : (
        <div style={{ maxWidth: 750 }}>
            <Card
                title={
                    <span>
                        <CloseButton
                            className="float-right"
                            onClick={() => {
                                setCohort({ id: false, groups: [] })
                                onChange()
                                router.actions.push(`${this.props.location.pathname}`)
                            }}
                        />
                        {cohort.name || 'New Cohort'}
                    </span>
                }
            >
                <form
                    className="card-body"
                    onSubmit={e => {
                        e.preventDefault()
                        saveCohort(cohort)
                    }}
                >
                    <input
                        style={{ marginBottom: '1rem' }}
                        required
                        className="form-control"
                        autoFocus
                        placeholder="Cohort name..."
                        value={cohort.name}
                        onChange={e => setCohort({ ...cohort, name: e.target.value })}
                    />
                    {cohort.groups
                        .map((group, index) => (
                            <CohortGroup
                                key={index}
                                group={group}
                                properties={personProperties}
                                index={index}
                                onRemove={() => {
                                    cohort.groups.splice(index, 1)
                                    setCohort({ ...cohort })
                                }}
                                onChange={group => {
                                    cohort.groups[index] = group
                                    setCohort({ ...cohort })
                                }}
                            />
                        ))
                        .reduce((prev, curr, index) => [
                            prev,
                            <div key={index} className="secondary" style={{ textAlign: 'center', margin: 8 }}>
                                {' '}
                                OR{' '}
                            </div>,
                            curr,
                        ])}

                    <Button
                        type="primary"
                        htmlType="submit"
                        disabled={isSubmitDisabled(cohort)}
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
                </form>
            </Card>
        </div>
    )
}
